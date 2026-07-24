# Minimal EC2 deployment (all-in-one box)

The lightweight alternative to [`deploy/terraform/`](../terraform/) (ECS Fargate
+ ALB + DynamoDB). Runs the whole service on one small EC2 instance, with SQLite
state on the instance's disk and automatic HTTPS. Roughly **3–4× cheaper** and
far fewer moving parts — a good fit for the initial deployment while traffic is
low. See [`docs/deployment-comparison.md`](../../docs/deployment-comparison.md)
for the cost/complexity breakdown.

When traffic grows and you need HA or multiple instances, switch
`PULSE_STORE_BACKEND=dynamodb` and promote to the Terraform stack — the app
abstracts state, so that's a config change, not a rewrite.

## What you get

- One `t4g.small` (arm64/Graviton, 2 vCPU / 2 GB) with a public IP.
- Two Docker containers on a private `pulse-net` network:
  - **`biothings-pulse`** — the app, published only on `127.0.0.1:8080`.
  - **`biothings-caddy`** — a [Caddy](https://caddyserver.com) reverse proxy on
    ports 80/443 that terminates HTTPS with an automatically provisioned +
    renewed **Let's Encrypt** certificate.
- Both run with `--restart unless-stopped`, so they survive crashes and reboots.
- Persistent state at `/var/lib/pulse` (SQLite DB + cloned plugin repos) and a
  `pulse-caddy-data` volume for certs — both survive redeploys.
- No container registry: the image is built **on the box** from source.

## Prerequisites

- An EC2 instance in a VPC with a public subnet + internet gateway. This account
  has **no default VPC** — use the existing **`biothings_vpc`**.
- Security group inbound: **22** (SSH), **80** (HTTP + ACME challenge), **443**
  (HTTPS). Port 80 must be open for Let's Encrypt to issue the cert.
- For HTTPS: a DNS **A record** for your domain pointing at the instance's public
  IP (e.g. `pulse.biothings.io → <public-ip>`), created **before** you deploy.

## Usage

### 1. Provision the instance

Either create it yourself in `biothings_vpc` (recommended for control), or use
the helper:

```bash
KEY_NAME=my-keypair ./deploy/ec2/launch.sh
# Resolves VPC by name (VPC_NAME=biothings_vpc), picks a public subnet, opens
# 22/80/443, launches a t4g.small. Restrict SSH with SSH_CIDR=<your-ip>/32.
```

### 2. Point DNS at the box

Create `pulse.biothings.io` → `<public-ip>` (A record) and wait for it to
resolve (`dig +short pulse.biothings.io`). Do this before step 3 so Caddy can
obtain the certificate on first boot.

### 3. Build + deploy

Pick whichever fits how you provisioned the box.

**A) On the box (you SSH in yourself)** — the self-contained one-liner. It
clones this repo, builds the image, and starts the app + Caddy:

```bash
curl -fsSL https://raw.githubusercontent.com/biothings/biothings_pulse/main/deploy/ec2/bootstrap.sh -o /tmp/pulse-setup.sh
DOMAIN=pulse.biothings.io ADMIN_TOKEN='a-strong-secret' bash /tmp/pulse-setup.sh
```

Omit `DOMAIN` to serve plain HTTP on port 80; omit `ADMIN_TOKEN` to keep the API
read-only.

**B) From your laptop (push-style)** — ships your *local* working copy over SSH
(handy for testing un-pushed changes):

```bash
HOST=<public-ip> SSH_KEY=~/.ssh/my-keypair.pem \
  DOMAIN=pulse.biothings.io ADMIN_TOKEN='a-strong-secret' ./deploy/ec2/deploy.sh
```

Either way, re-run to deploy an update in place — state in `/var/lib/pulse` and
the TLS cert are preserved.

### 4. Operate

```bash
ssh ec2-user@<ip> 'sudo docker ps'
ssh ec2-user@<ip> 'sudo docker logs -f biothings-pulse'   # app logs
ssh ec2-user@<ip> 'sudo docker logs -f biothings-caddy'   # proxy / cert logs
ssh ec2-user@<ip> 'sudo docker restart biothings-pulse'
```

## Configuration knobs

| Script | Env var | Default | Purpose |
|---|---|---|---|
| launch | `KEY_NAME` | *(required)* | Existing EC2 key pair |
| launch | `VPC_NAME` | `biothings_vpc` | VPC to launch into (or set `VPC_ID`) |
| launch | `SUBNET_ID` | *(auto)* | Public subnet in the VPC |
| launch | `INSTANCE_TYPE` | `t4g.small` | Instance size (arm64) |
| launch | `VOLUME_SIZE` | `20` | Root EBS size (GB) |
| launch | `SSH_CIDR` | `0.0.0.0/0` | Who may SSH — **restrict this** |
| bootstrap / deploy | `DOMAIN` | *(empty)* | FQDN for automatic HTTPS; empty ⇒ HTTP:80 |
| bootstrap / deploy | `ADMIN_TOKEN` | *(empty)* | `PULSE_ADMIN_TOKEN`; empty ⇒ read-only |
| bootstrap / deploy | `DATA_DIR` | `/var/lib/pulse` | Persistent state on the host |
| bootstrap | `PULSE_REF` | `main` | Git branch/tag/commit to deploy |
| deploy | `HOST` | *(required)* | Instance IP/DNS |
| deploy | `SSH_KEY` / `SSH_USER` | *(agent)* / `ec2-user` | SSH connection |

## How HTTPS works

`run.sh` starts Caddy with `PULSE_SITE_ADDRESS` set to your `DOMAIN`. Caddy then
solves the ACME HTTP-01 challenge on port 80, installs the cert, redirects
HTTP→HTTPS, and renews automatically — no cron, no certbot. Certs live in the
`pulse-caddy-data` Docker volume, so container replacements don't re-issue.
If HTTPS briefly 502s right after deploy, Caddy is still issuing the cert;
recheck in ~30s. To add a contact email for expiry notices, see the note in
[`Caddyfile`](Caddyfile).

## Tear down

```bash
aws --region us-west-2 ec2 terminate-instances --instance-ids <instance-id>
```
