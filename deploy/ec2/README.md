# Minimal EC2 deployment (all-in-one box)

The lightweight alternative to [`deploy/terraform/`](../terraform/) (ECS Fargate
+ ALB + DynamoDB). Runs the whole service as a single Docker container on one
small EC2 instance, with SQLite state on the instance's disk. Roughly **3–4×
cheaper** and far fewer moving parts — a good fit for the initial deployment
while traffic is low. See [`docs/deployment-comparison.md`](../../docs/deployment-comparison.md)
for the cost/complexity breakdown.

When traffic grows and you need HA, managed TLS, or more than one instance,
switch `PULSE_STORE_BACKEND=dynamodb` and promote to the Terraform stack — the
app abstracts state, so that's a config change, not a rewrite.

## What you get

- One `t4g.small` (arm64/Graviton, 2 vCPU / 2 GB), public IP, ports 22/80/443.
- Pulse in a Docker container, published on port 80 (`http://<ip>/`).
- Managed by a `systemd` unit (`biothings-pulse.service`) with `Restart=always`,
  so it survives crashes and reboots.
- Persistent state at `/var/lib/pulse` (SQLite DB + cloned plugin repos),
  bind-mounted into the container so redeploys keep version history.
- No container registry: the image is built **on the box** from shipped source
  (host Mac and the Graviton box are both arm64).

## Prerequisites

- AWS CLI v2 with credentials (only for `launch.sh`; skip if you already have a box).
- An existing EC2 key pair.
- Docker on your machine is **not** required — the build happens on the instance.

## Usage

### 1. Provision the instance (optional)

```bash
KEY_NAME=my-keypair ./deploy/ec2/launch.sh
# ...prints the public IP. Restrict SSH with SSH_CIDR=<your-ip>/32.
```

Skip this step if you already have an Amazon Linux 2023 (or Debian/Ubuntu) host.

### 2. Build + deploy the app

```bash
HOST=<public-ip> SSH_KEY=~/.ssh/my-keypair.pem ./deploy/ec2/deploy.sh
```

This ships the source, builds the image on the host, installs the systemd unit,
starts it, and waits for `GET /api/health` to pass. Re-run it any time to deploy
an update in place — state in `/var/lib/pulse` is preserved.

To enable admin/mutating operations, pass a secret (otherwise the API is
read-only):

```bash
HOST=<ip> SSH_KEY=~/.ssh/key.pem ADMIN_TOKEN='a-strong-secret' ./deploy/ec2/deploy.sh
```

To monitor a smaller set of repos, ship a custom registry YAML:

```bash
HOST=<ip> SSH_KEY=~/.ssh/key.pem \
  REGISTRY_FILE=./my-repos.yaml ./deploy/ec2/deploy.sh
```

### 3. Operate

```bash
ssh ec2-user@<ip> 'sudo systemctl status biothings-pulse'
ssh ec2-user@<ip> 'sudo journalctl -u biothings-pulse -f'     # follow logs
ssh ec2-user@<ip> 'sudo systemctl restart biothings-pulse'
```

## Configuration knobs

| Script | Env var | Default | Purpose |
|---|---|---|---|
| launch | `KEY_NAME` | *(required)* | Existing EC2 key pair |
| launch | `AWS_REGION` | `us-west-2` | Region |
| launch | `INSTANCE_TYPE` | `t4g.small` | Instance size (arm64) |
| launch | `VOLUME_SIZE` | `20` | Root EBS size (GB) |
| launch | `SSH_CIDR` | `0.0.0.0/0` | Who may SSH — **restrict this** |
| deploy | `HOST` | *(required)* | Instance IP/DNS |
| deploy | `SSH_KEY` | *(agent)* | Path to the private key |
| deploy | `SSH_USER` | `ec2-user` | `admin`/`ubuntu` on Debian/Ubuntu |
| deploy | `HTTP_PORT` | `80` | Host port mapped to container 8080 |
| deploy | `DATA_DIR` | `/var/lib/pulse` | Persistent state on the host |
| deploy | `ADMIN_TOKEN` | *(empty)* | `PULSE_ADMIN_TOKEN`; empty ⇒ read-only |
| deploy | `REGISTRY_FILE` | *(bundled)* | Local registry YAML to ship |

## Adding HTTPS (optional)

The box exposes port 443 but terminates plain HTTP by default. For TLS with a
real domain, put [Caddy](https://caddyserver.com) in front (automatic Let's
Encrypt): point `HTTP_PORT` at `8080`, then run Caddy on the host reverse-proxying
`your.domain → 127.0.0.1:8080`. This keeps the box all-in-one without an ALB.

## Tear down

```bash
aws --region us-west-2 ec2 terminate-instances --instance-ids <instance-id>
```
