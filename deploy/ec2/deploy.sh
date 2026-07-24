#!/usr/bin/env bash
# Build + (re)deploy BioThings Pulse onto a single Linux box over SSH.
#
# This is the minimal counterpart to `terraform apply`: it ships the repo
# source to the host, builds the Docker image there (host and a Graviton box
# are both arm64), and runs it under a systemd unit with a persistent data
# volume and a restart policy. Re-running it performs an in-place update.
#
# No container registry required. Works against a box created by launch.sh or
# any pre-existing Amazon Linux 2023 / Debian host you can SSH into (Docker is
# installed automatically if missing).
#
# Usage:
#   HOST=<ip-or-dns> SSH_KEY=~/.ssh/key.pem ./deploy/ec2/deploy.sh
#
# Tunables (env vars, with defaults):
#   SSH_USER=ec2-user            # 'admin'/'ubuntu' on Debian/Ubuntu
#   HTTP_PORT=80                 # host port -> container 8080 (hit http://HOST/)
#   DATA_DIR=/var/lib/pulse      # persistent SQLite DB + cloned repos on the host
#   ADMIN_TOKEN=<secret>         # sets PULSE_ADMIN_TOKEN (empty => admin disabled)
#   REGISTRY_FILE=<path>         # local registry YAML to ship (else bundled default)
#   IMAGE_TAG=biothings-pulse:latest
set -euo pipefail

: "${HOST:?Set HOST to the instance IP or DNS name}"
SSH_USER="${SSH_USER:-ec2-user}"
HTTP_PORT="${HTTP_PORT:-80}"
DATA_DIR="${DATA_DIR:-/var/lib/pulse}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
REGISTRY_FILE="${REGISTRY_FILE:-}"
IMAGE_TAG="${IMAGE_TAG:-biothings-pulse:latest}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_DIR=/opt/biothings-pulse

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")
TARGET="${SSH_USER}@${HOST}"

run() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }

echo "==> [1/5] Ensuring Docker is installed on $HOST ..."
run 'command -v docker >/dev/null 2>&1 || {
  if command -v dnf >/dev/null 2>&1; then sudo dnf install -y docker;
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y docker.io;
  else echo "unsupported OS: install Docker manually" >&2; exit 1; fi;
}
sudo systemctl enable --now docker'

echo "==> [2/5] Shipping source to ${SRC_DIR} ..."
run "sudo install -d -m 0755 ${SRC_DIR} ${DATA_DIR} && sudo chown \$(id -u):\$(id -g) ${SRC_DIR}"
# Only the build context the Dockerfile needs; exclude local venv/cache/git.
tar -C "$REPO_ROOT" -czf - \
  --exclude='.venv' --exclude='.cache' --exclude='.git' --exclude='__pycache__' \
  pyproject.toml README.md src scripts deploy \
  | run "tar -xzf - -C ${SRC_DIR}"

# Optionally override the plugin registry with a local YAML (mounted at run time).
if [ -n "$REGISTRY_FILE" ]; then
  echo "    Shipping registry file $REGISTRY_FILE"
  scp "${SSH_OPTS[@]}" "$REGISTRY_FILE" "${TARGET}:/tmp/pulse-registry.yaml"
  run "sudo mv /tmp/pulse-registry.yaml ${SRC_DIR}/registry.yaml"
fi

echo "==> [3/5] Building image ${IMAGE_TAG} on the host ..."
run "cd ${SRC_DIR} && sudo docker build -f deploy/Dockerfile -t ${IMAGE_TAG} ."

echo "==> [4/5] Installing systemd unit ..."
# The container serves on 8080; publish it on HTTP_PORT. State persists via the
# host bind-mount, so container replacements keep versions/timestamps.
ADMIN_ENV=""
[ -n "$ADMIN_TOKEN" ] && ADMIN_ENV="-e PULSE_ADMIN_TOKEN=${ADMIN_TOKEN}"
# Mount a shipped registry.yaml into the container and point Pulse at it.
REGISTRY_ARGS=""
[ -n "$REGISTRY_FILE" ] && REGISTRY_ARGS="-v ${SRC_DIR}/registry.yaml:/app/registry.yaml:ro -e PULSE_REGISTRY_FILE=/app/registry.yaml"

run "sudo tee /etc/systemd/system/biothings-pulse.service >/dev/null" <<EOF
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
  ${ADMIN_ENV} ${REGISTRY_ARGS} \\
  ${IMAGE_TAG}
ExecStop=/usr/bin/docker stop biothings-pulse

[Install]
WantedBy=multi-user.target
EOF

echo "==> [5/5] Starting service ..."
run "sudo systemctl daemon-reload && sudo systemctl enable --now biothings-pulse && sudo systemctl restart biothings-pulse"

echo "==> Deployed. Waiting for health check ..."
for i in $(seq 1 30); do
  if curl -fsS "http://${HOST}:${HTTP_PORT}/api/health" >/dev/null 2>&1; then
    echo "    Healthy: http://${HOST}:${HTTP_PORT}/api/health"
    echo "    Dashboard: http://${HOST}:${HTTP_PORT}/"
    echo "    API docs:  http://${HOST}:${HTTP_PORT}/api/docs"
    exit 0
  fi
  sleep 3
done
echo "!! Health check did not pass in time. Inspect logs with:" >&2
echo "   ssh ${TARGET} 'sudo journalctl -u biothings-pulse -n 100 --no-pager'" >&2
exit 1
