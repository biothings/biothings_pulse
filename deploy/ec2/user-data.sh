#!/usr/bin/env bash
# Cloud-init user-data for a minimal BioThings Pulse box (Amazon Linux 2023).
#
# Runs once on first boot. It only prepares the host — installs Docker and the
# persistent data dir. The application image is built + started later by
# deploy/ec2/deploy.sh (which ships the source and runs `docker build` here).
#
# Referenced by launch.sh; you normally don't run this by hand.
set -euxo pipefail

dnf update -y
dnf install -y docker tar gzip
systemctl enable --now docker

# Let ec2-user drive docker without sudo (takes effect on next login).
usermod -aG docker ec2-user || true

# Persistent state (SQLite DB + cloned repos) lives here, on the root EBS volume.
install -d -m 0755 /var/lib/pulse
# Build context lands here (deploy.sh unpacks the source into it).
install -d -m 0755 /opt/biothings-pulse
