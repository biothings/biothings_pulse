#!/usr/bin/env bash
# On-box setup for a minimal BioThings Pulse deployment.
#
# Run this ON a fresh EC2 instance (Amazon Linux 2023, or Debian/Ubuntu) after
# you SSH in. It installs Docker + git, clones this repo, builds the image on
# the box, and runs it under a systemd unit with a persistent data volume and a
# restart policy. Safe to re-run — it updates in place and preserves state.
#
#   curl -fsSL https://raw.githubusercontent.com/biothings/biothings_pulse/main/deploy/ec2/bootstrap.sh -o /tmp/pulse-setup.sh
#   bash /tmp/pulse-setup.sh
#
# Options (environment variables):
#   ADMIN_TOKEN=<secret>   enable admin/mutating ops (default: empty => read-only)
#   HTTP_PORT=80           host port mapped to the container's 8080
#   DATA_DIR=/var/lib/pulse persistent SQLite DB + cloned plugin repos
#   PULSE_REF=main         git branch / tag / commit to deploy
#   REPO_URL=<url>         source repo (default: biothings/biothings_pulse)
set -euo pipefail

ADMIN_TOKEN="${ADMIN_TOKEN:-}"
HTTP_PORT="${HTTP_PORT:-80}"
DATA_DIR="${DATA_DIR:-/var/lib/pulse}"
PULSE_REF="${PULSE_REF:-main}"
REPO_URL="${REPO_URL:-https://github.com/biothings/biothings_pulse.git}"
SRC_DIR="${SRC_DIR:-/opt/biothings-pulse}"
IMAGE_TAG=biothings-pulse:latest

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

install_pkgs() {
  if command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y "$@"
  elif command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -y && $SUDO apt-get install -y "$@"
  else echo "unsupported OS; install $* manually" >&2; exit 1; fi
}

echo "==> [1/5] Installing Docker + git ..."
command -v docker >/dev/null 2>&1 || install_pkgs docker
command -v git   >/dev/null 2>&1 || install_pkgs git
$SUDO systemctl enable --now docker

echo "==> [2/5] Fetching source ($REPO_URL @ $PULSE_REF) into $SRC_DIR ..."
$SUDO install -d -m 0755 "$SRC_DIR" "$DATA_DIR"
$SUDO chown "$(id -u):$(id -g)" "$SRC_DIR"
if [ -d "$SRC_DIR/.git" ]; then
  git -C "$SRC_DIR" fetch --depth 1 origin "$PULSE_REF"
  git -C "$SRC_DIR" checkout -f FETCH_HEAD
else
  # Try a shallow branch/tag clone; fall back to full clone + checkout for a commit SHA.
  git clone --depth 1 --branch "$PULSE_REF" "$REPO_URL" "$SRC_DIR" 2>/dev/null \
    || { git clone "$REPO_URL" "$SRC_DIR" && git -C "$SRC_DIR" checkout -f "$PULSE_REF"; }
fi

echo "==> [3/5] Building image $IMAGE_TAG on the box (this can take a few minutes) ..."
( cd "$SRC_DIR" && $SUDO docker build -f deploy/Dockerfile -t "$IMAGE_TAG" . )

echo "==> [4/5] Installing systemd unit ..."
ADMIN_ENV=""
[ -n "$ADMIN_TOKEN" ] && ADMIN_ENV="-e PULSE_ADMIN_TOKEN=${ADMIN_TOKEN}"
$SUDO tee /etc/systemd/system/biothings-pulse.service >/dev/null <<EOF
[Unit]
Description=BioThings Pulse
After=docker.service
Requires=docker.service

[Service]
Restart=always
RestartSec=5
# Fresh container each start; state lives in the ${DATA_DIR} bind-mount.
ExecStartPre=-/usr/bin/docker rm -f biothings-pulse
ExecStart=/usr/bin/docker run --rm --name biothings-pulse \\
  -p ${HTTP_PORT}:8080 \\
  -v ${DATA_DIR}:/data \\
  ${ADMIN_ENV} \\
  ${IMAGE_TAG}
ExecStop=/usr/bin/docker stop biothings-pulse

[Install]
WantedBy=multi-user.target
EOF

echo "==> [5/5] Starting service ..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable biothings-pulse
$SUDO systemctl restart biothings-pulse

echo "==> Waiting for health check ..."
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/health" >/dev/null 2>&1; then
    IP="$(curl -fsS http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<public-ip>')"
    echo
    echo "    Healthy!"
    echo "    Dashboard: http://${IP}:${HTTP_PORT}/"
    echo "    API docs:  http://${IP}:${HTTP_PORT}/api/docs"
    echo "    Logs:      sudo journalctl -u biothings-pulse -f"
    exit 0
  fi
  sleep 3
done
echo "!! Health check did not pass in time. Inspect logs with:" >&2
echo "   sudo journalctl -u biothings-pulse -n 100 --no-pager" >&2
exit 1
