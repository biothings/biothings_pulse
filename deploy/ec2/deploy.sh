#!/usr/bin/env bash
# Build + (re)deploy BioThings Pulse onto a single Linux box over SSH.
#
# The minimal counterpart to `terraform apply`: it ships the repo source to the
# host, installs Docker if needed, then builds + runs the stack (Pulse app +
# Caddy reverse proxy, with optional HTTPS) via run.sh. Re-run to update in
# place; state under DATA_DIR and TLS certs persist.
#
# Unlike bootstrap.sh (which the box fetches from GitHub and runs itself), this
# pushes your *local* working copy — handy for testing un-pushed changes.
#
# Usage:
#   HOST=<ip-or-dns> SSH_KEY=~/.ssh/key.pem ./deploy/ec2/deploy.sh
#   # with HTTPS + admin:
#   HOST=<ip> SSH_KEY=~/.ssh/key.pem DOMAIN=pulse.biothings.io \
#     ADMIN_TOKEN='a-strong-secret' ./deploy/ec2/deploy.sh
#
# Tunables (env vars, with defaults):
#   SSH_USER=ec2-user            # 'admin'/'ubuntu' on Debian/Ubuntu
#   DOMAIN=<fqdn>                # enable automatic HTTPS (empty => plain HTTP:80)
#   DATA_DIR=/var/lib/pulse      # persistent SQLite DB + cloned repos on the host
#   ADMIN_TOKEN=<secret>         # PULSE_ADMIN_TOKEN (empty => admin disabled)
set -euo pipefail

: "${HOST:?Set HOST to the instance IP or DNS name}"
SSH_USER="${SSH_USER:-ec2-user}"
DOMAIN="${DOMAIN:-}"
DATA_DIR="${DATA_DIR:-/var/lib/pulse}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_DIR=/opt/biothings-pulse

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")
TARGET="${SSH_USER}@${HOST}"
run() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }

echo "==> [1/3] Ensuring Docker is installed on $HOST ..."
run 'command -v docker >/dev/null 2>&1 || {
  if command -v dnf >/dev/null 2>&1; then sudo dnf install -y docker;
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y docker.io;
  else echo "unsupported OS: install Docker manually" >&2; exit 1; fi;
}
sudo systemctl enable --now docker'

echo "==> [2/3] Shipping source to ${SRC_DIR} ..."
run "sudo install -d -m 0755 ${SRC_DIR} && sudo chown \$(id -u):\$(id -g) ${SRC_DIR}"
tar -C "$REPO_ROOT" -czf - \
  --exclude='.venv' --exclude='.cache' --exclude='.git' --exclude='__pycache__' \
  pyproject.toml README.md src scripts deploy \
  | run "tar -xzf - -C ${SRC_DIR}"

echo "==> [3/3] Building + starting the stack on the host ..."
# Pass config through to run.sh; quote to survive the remote shell.
run "cd ${SRC_DIR} && DOMAIN=$(printf %q "$DOMAIN") ADMIN_TOKEN=$(printf %q "$ADMIN_TOKEN") DATA_DIR=$(printf %q "$DATA_DIR") SRC_DIR=${SRC_DIR} bash deploy/ec2/run.sh"
