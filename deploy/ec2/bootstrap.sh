#!/usr/bin/env bash
# On-box setup for a minimal BioThings Pulse deployment (with optional HTTPS).
#
# Run this ON a fresh EC2 instance (Amazon Linux 2023, or Debian/Ubuntu) after
# you SSH in. It installs Docker + git, clones this repo, then builds and runs
# the stack (Pulse app + Caddy reverse proxy) via run.sh. Safe to re-run — it
# updates in place; state and TLS certs persist.
#
#   curl -fsSL https://raw.githubusercontent.com/biothings/biothings_pulse/main/deploy/ec2/bootstrap.sh -o /tmp/pulse-setup.sh
#   bash /tmp/pulse-setup.sh
#
# For HTTPS, point your domain's A record at this instance first, then:
#   DOMAIN=pulse.biothings.io ADMIN_TOKEN='a-strong-secret' bash /tmp/pulse-setup.sh
#
# Options (environment variables):
#   DOMAIN=<fqdn>          enable automatic HTTPS (Let's Encrypt via Caddy)
#   ADMIN_TOKEN=<secret>   enable admin/mutating ops (default: empty => read-only)
#   DATA_DIR=/var/lib/pulse persistent SQLite DB + cloned plugin repos
#   PULSE_REF=main         git branch / tag / commit to deploy
#   REPO_URL=<url>         source repo (default: biothings/biothings_pulse)
set -euo pipefail

PULSE_REF="${PULSE_REF:-main}"
REPO_URL="${REPO_URL:-https://github.com/biothings/biothings_pulse.git}"
SRC_DIR="${SRC_DIR:-/opt/biothings-pulse}"
export DATA_DIR="${DATA_DIR:-/var/lib/pulse}"
export SRC_DIR   # run.sh builds from here
# DOMAIN / ADMIN_TOKEN pass through the environment to run.sh.

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

install_pkgs() {
  if command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y "$@"
  elif command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -y && $SUDO apt-get install -y "$@"
  else echo "unsupported OS; install $* manually" >&2; exit 1; fi
}

echo "==> [1/3] Installing Docker + git ..."
command -v docker >/dev/null 2>&1 || install_pkgs docker
command -v git   >/dev/null 2>&1 || install_pkgs git
$SUDO systemctl enable --now docker

echo "==> [2/3] Fetching source ($REPO_URL @ $PULSE_REF) into $SRC_DIR ..."
$SUDO install -d -m 0755 "$SRC_DIR"
$SUDO chown "$(id -u):$(id -g)" "$SRC_DIR"
if [ -d "$SRC_DIR/.git" ]; then
  git -C "$SRC_DIR" fetch --depth 1 origin "$PULSE_REF"
  git -C "$SRC_DIR" checkout -f FETCH_HEAD
else
  git clone --depth 1 --branch "$PULSE_REF" "$REPO_URL" "$SRC_DIR" 2>/dev/null \
    || { git clone "$REPO_URL" "$SRC_DIR" && git -C "$SRC_DIR" checkout -f "$PULSE_REF"; }
fi

echo "==> [3/3] Building + starting the stack ..."
bash "$SRC_DIR/deploy/ec2/run.sh"
