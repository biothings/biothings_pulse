# Deployment options: minimal EC2 vs. Terraform/Fargate

A comparison for the **initial** BioThings Pulse deployment. No infra changes
are made by this document — it only weighs the two paths.

## TL;DR

| | **Minimal EC2 (all-in-one)** | **Terraform → ECS Fargate (current `deploy/terraform`)** |
|---|---|---|
| Est. cost / month | **~$12–17** | **~$45–60** |
| Time to first deploy | ~30–60 min, mostly manual | ~15 min once AWS creds + Docker image are ready |
| Moving parts | 1 VM + Docker | ECR, ECS cluster, Fargate task, ALB, DynamoDB, 2× IAM roles, 2× security groups, CloudWatch |
| Reproducible / versioned | No (unless you script it) | Yes (IaC, in git) |
| Scales past 1 instance | No | Yes (raise `desired_count`, flip to EventBridge scheduler) |
| Ops burden | You patch the OS, restart the container | AWS manages the runtime |
| Best for | Getting a URL up now; low-stakes / internal | Long-lived production, HA, team ownership |

**Recommendation:** for the *initial* stand-up, a **minimal EC2 instance** is
the pragmatic choice — it's ~3–4× cheaper and matches Pulse's actual load
(one lightweight process, a handful of HTTP `HEAD`s per day, a tiny state DB).
Keep the existing Terraform stack as the **production** target and promote to it
once the service needs HA, a stable DNS/TLS endpoint, or more than one instance.
The app already supports both cleanly (SQLite ↔ DynamoDB via `PULSE_STORE_BACKEND`).

---

## Why Pulse is a good fit for a single small VM

The workload is deliberately light:

- Checks are a few HTTP `HEAD` / FTP `MDTM` calls per source, **no downloads**.
- Default cadence is **daily**, scheduler wakes hourly to find due sources.
- State is a small SQLite file (hundreds of rows), reads are cached — polling
  never triggers a check.

A burstable `t4g.small` (2 vCPU, 2 GB, ARM) idles almost all day and bursts
briefly during a check sweep. There is no need for a load balancer or a
container orchestrator to run one such process.

## Option A — Minimal EC2 (everything on one box)

**Shape:** one `t4g.small` (or `t3.micro` if you want to shave a few dollars),
Amazon Linux 2023, Docker installed, run the Pulse image with
`--restart=unless-stopped`. SQLite state on the instance's EBS volume. Optional
Caddy/nginx in front for TLS if you want HTTPS + a domain.

**Config:** keep the local defaults — `PULSE_STORE_BACKEND=sqlite`,
`PULSE_SQLITE_PATH` and `PULSE_CACHE_DIR` on a persistent path (e.g.
`/var/lib/pulse`), in-app scheduler enabled (`desired_count` is effectively 1).

**Cost (us-west-2, on-demand, ~730 h/mo):**

| Item | Est. / mo |
|---|---|
| `t4g.small` (2 vCPU, 2 GB) | ~$12 |
| 20 GB gp3 EBS | ~$1.60 |
| 1 public IPv4 | ~$3.60 |
| **Total** | **~$17** |

(`t3.micro` drops the compute to ~$7.60 → **~$13/mo** total; Savings Plan or a
1-yr reservation cuts compute a further ~30–40%.)

**Pros**
- Cheapest; simplest mental model — SSH in, `docker logs`, `docker restart`.
- Nothing new to learn; identical to `docker run` in local dev.
- SQLite path already works out of the box.

**Cons**
- Manual: you provision, patch the OS, and re-deploy by hand (or write a small
  script/user-data). Not captured as code unless you add it.
- Single point of failure; a stop/replace loses in-instance state unless the
  EBS volume is preserved or you snapshot it.
- No managed TLS/DNS — you add Caddy + a domain yourself for HTTPS.
- Scaling out means re-architecting (this is the Fargate stack's job).

## Option B — Terraform → ECS Fargate (already written)

**Shape:** `deploy/terraform/main.tf` provisions ECR, an ECS Fargate service
(0.5 vCPU / 1 GB, 1 task) behind an ALB, a DynamoDB state table
(pay-per-request), CloudWatch logs (30-day retention), two IAM roles, and two
security groups. Health check now hits `/api/health`.

**Cost (us-west-2, on-demand):**

| Item | Est. / mo |
|---|---|
| Fargate task 0.5 vCPU + 1 GB, 24×7 | ~$18 |
| Application Load Balancer (base + low LCU) | ~$18–20 |
| Public IPv4s (ALB + task) | ~$7–11 |
| DynamoDB (pay-per-request, tiny) | <$1 |
| CloudWatch logs + ECR storage | ~$1 |
| **Total** | **~$45–60** |

The **ALB (~$18–20) is the single biggest cost** and buys little for one
instance — it mainly matters once you run ≥2 tasks or need managed TLS via ACM.

**Pros**
- Fully reproducible, versioned in git; `terraform apply` re-creates everything.
- AWS manages the runtime; task restarts/replaces on failure.
- Clear path to HA: raise `desired_count`, set `PULSE_SCHEDULER_ENABLED=false`,
  drive refreshes from EventBridge (already sketched in `main.tf`).
- DynamoDB removes any state-durability concern.

**Cons**
- ~3–4× the cost, dominated by the ALB, for a workload that doesn't need it yet.
- More moving parts to understand/debug for a first deploy.
- Requires the Terraform + ECS/Fargate learning curve and AWS creds wired up.

---

## Suggested path

1. **Now:** deploy Option A (minimal EC2) to get a live URL cheaply. Persist
   `/var/lib/pulse` on its own EBS volume and enable admin only if needed
   (`PULSE_ADMIN_TOKEN` from SSM/instance profile, not a plaintext value).
2. **When it graduates to production** (HA, TLS + real DNS, multi-instance, or
   team ownership): switch `PULSE_STORE_BACKEND=dynamodb` and apply the existing
   Terraform stack. If cost is still a concern there, the biggest lever is
   dropping the ALB — front a single task with CloudFront or a lightweight
   proxy — but that's a later optimization.

Because Pulse already abstracts state (SQLite ↔ DynamoDB) and reads config from
`PULSE_*` env vars, moving from A to B is a config change plus a Terraform apply,
not a rewrite.
