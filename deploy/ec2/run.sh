#!/usr/bin/env bash
# Shared on-box logic: build the image and (re)run the two-container stack
# (Pulse app + Caddy reverse proxy) with a persistent data volume and a restart
# policy. Called by bootstrap.sh (on-box clone) and deploy.sh (laptop push).
# Safe to re-run — it recreates the containers; state and TLS certs persist.
#
# Env vars:
#   ADMIN_TOKEN=<secret>   enable admin ops (default: empty => read-only API)
#   DOMAIN=<fqdn>          e.g. pulse.biothings.io -> automatic HTTPS via Caddy.
#                          Empty => plain HTTP on port 80.
#   DATA_DIR=/var/lib/pulse persistent SQLite DB + cloned plugin repos
#   SRC_DIR=<repo path>    build context (default: repo root inferred from $0)
#   IMAGE_TAG=biothings-pulse:latest
set -euo pipefail

ADMIN_TOKEN="${ADMIN_TOKEN:-}"
DOMAIN="${DOMAIN:-}"
DATA_DIR="${DATA_DIR:-/var/lib/pulse}"
SRC_DIR="${SRC_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
IMAGE_TAG="${IMAGE_TAG:-biothings-pulse:latest}"
NET=pulse-net

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
D() { $SUDO docker "$@"; }

echo "==> Building image $IMAGE_TAG (this can take a few minutes) ..."
$SUDO install -d -m 0755 "$DATA_DIR"
( cd "$SRC_DIR" && D build -f deploy/Dockerfile -t "$IMAGE_TAG" . )

echo "==> Ensuring docker network $NET ..."
D network inspect "$NET" >/dev/null 2>&1 || D network create "$NET"

echo "==> (Re)starting the Pulse app container ..."
ADMIN_ARGS=()
[ -n "$ADMIN_TOKEN" ] && ADMIN_ARGS=(-e "PULSE_ADMIN_TOKEN=${ADMIN_TOKEN}")
D rm -f biothings-pulse >/dev/null 2>&1 || true
# Published only on loopback: reachable for local health checks, never public.
# Caddy reaches it over the docker network as "biothings-pulse:8080".
D run -d --restart unless-stopped --name biothings-pulse --network "$NET" \
  -p 127.0.0.1:8080:8080 \
  -v "${DATA_DIR}:/data" \
  "${ADMIN_ARGS[@]}" \
  "$IMAGE_TAG"

echo "==> (Re)starting the Caddy reverse proxy ..."
if [ -n "$DOMAIN" ]; then
  SITE="$DOMAIN"; PORTS=(-p 80:80 -p 443:443)
  echo "    TLS mode: Caddy will obtain a Let's Encrypt cert for $DOMAIN."
  echo "    (Requires $DOMAIN to resolve to this instance and inbound 80+443 open.)"
else
  SITE=":80"; PORTS=(-p 80:80)
  echo "    HTTP mode (no DOMAIN set): serving plain HTTP on port 80."
fi
D rm -f biothings-caddy >/dev/null 2>&1 || true
D run -d --restart unless-stopped --name biothings-caddy --network "$NET" \
  "${PORTS[@]}" \
  -e "PULSE_SITE_ADDRESS=${SITE}" \
  -v "${SRC_DIR}/deploy/ec2/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v pulse-caddy-data:/data \
  -v pulse-caddy-config:/config \
  caddy:2-alpine

echo "==> Waiting for the app health check ..."
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null 2>&1; then
    if [ -n "$DOMAIN" ]; then URL="https://$DOMAIN"; else
      IP="$(curl -fsS http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<public-ip>')"
      URL="http://$IP"
    fi
    echo
    echo "    App is healthy."
    echo "    Dashboard: ${URL}/"
    echo "    API docs:  ${URL}/api/docs"
    [ -n "$DOMAIN" ] && echo "    (If HTTPS 502s briefly, Caddy is still issuing the cert — recheck in ~30s.)"
    echo "    Logs:      sudo docker logs -f biothings-pulse   |   sudo docker logs -f biothings-caddy"
    exit 0
  fi
  sleep 3
done
echo "!! App health check did not pass in time. Inspect logs with:" >&2
echo "   sudo docker logs --tail 100 biothings-pulse" >&2
exit 1
