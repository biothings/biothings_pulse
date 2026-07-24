# BioThings Pulse

A standalone, production-ready API server that runs **only the data-source-check
step** of a [BioThings Hub](https://docs.biothings.io) data plugin — without
standing up a full Hub — and reports, per source:

1. **What is the current upstream version?** (`current_version`, and when it was
   first detected — `current_version_at`)
2. **What was the previous version?** (`last_version` / `last_version_at`)
3. *(Optional)* the list of **download URLs** the plugin would fetch.

Pulse only reports these observed facts. It does **not** decide whether *you*
need to update — each downstream hub/app polls the API and compares
`current_version` against its own deployed version to maintain its own state.

It supports both **manifest-based** plugins (`plugins/*/manifest.json`) and
**advanced** plugins (`.../hub/dataload/sources/<src>/`, and `plugins/<src>/`),
sourced from configurable `biothings`-org GitHub repos.

## How the version check works

Pulse reuses the BioThings SDK's own dumper logic — it never reimplements
version detection, so it stays faithful to each plugin's real behaviour.

For a single source, one check does this:

1. **Load the plugin's dumper.** A config shim points the SDK at file-based
   SQLite, so no MongoDB / running Hub is needed
   (`src/biothings_pulse/bootstrap.py`).
   - **Manifest plugin** — Pulse reads `manifest.json` and builds the dumper the
     same way the SDK loader does: `data_url` → `SRC_URLS`, and the base class is
     chosen by URL scheme (`LastModifiedHTTPDumper` for http/https,
     `LastModifiedFTPDumper` for ftp), or the explicit `class` if declared.
   - **Advanced plugin** — Pulse imports the source package and instantiates its
     `BaseDumper` subclass.
2. **Detect the release without downloading.** Pulse calls
   `create_todump_list(force=True)`, which triggers `set_release()` and a
   per-URL freshness comparison but **downloads no data**. Where the version
   comes from depends on the plugin:
   - **Last-Modified / ETag** (manifest with no `release`, or a `LastModified*`
     dumper): an HTTP `HEAD` reads the `Last-Modified` header (falling back to
     `ETag`); FTP uses the `MDTM` command.
   - **Custom `release` function** (manifest `"release": "module:func"`): that
     function is imported from the plugin and executed to produce the version.
   - **Advanced dumper**: whatever the plugin's own `set_release()` does.
3. **Read the result.** the detected version = `dumper.release`; `download_urls`
   = the remote URLs the dumper queued in `dumper.to_dump`.

**Recording versions.** Pulse tracks only what it has observed upstream:

- On a successful check, the detected version becomes `current_version`, stamped
  with `current_version_at` = **when it was first seen**.
- When a later check detects a **different** version, the old one rotates into
  `last_version` / `last_version_at` and the new one becomes `current_version`
  (with a fresh `current_version_at`). An unchanged version leaves the timestamps
  untouched.
- There is **no Pulse-side "update" flag or acknowledge step** — consumers decide
  what counts as an update for them by comparing `current_version` against their
  own deployed version.

Each check is isolated: a failing or uncheckable plugin is recorded with
`status: error` / `unsupported` and never affects other sources. Results are
persisted to the state store (SQLite locally, DynamoDB on AWS).

## How often it refreshes

Checks are cheap (a few HTTP `HEAD`s, no downloads). Reads never trigger a check,
so consumers can poll freely; checks happen only via the scheduler or explicitly.

- **Per-plugin schedule, else default.** A plugin may declare its own check
  schedule — a cron string in the manifest `dumper.schedule` or an advanced
  dumper's `SCHEDULE`. Pulse honors it. Sources without one are checked every
  `PULSE_SCHEDULER_INTERVAL` seconds (default **86400 s / daily**).
- **The scheduler is due-based.** When `PULSE_SCHEDULER_ENABLED=true` (default),
  it wakes every `PULSE_SCHEDULER_TICK` seconds (default **3600 s / hourly**) and
  checks only the sources that are *due* per their schedule. A never-checked
  source is always due, so a fresh deployment fills in on the first tick; a warm
  store (state persists) only re-checks what's actually due.
- **On demand.** `GET /sources/{repo}/{plugin}` returns the cached status without
  checking. `POST /sources/{repo}/{plugin}/check` forces one source now;
  `POST /admin/refresh` force-checks every source.
- **On startup.** If `PULSE_SYNC_ON_STARTUP=true` (default), Pulse git-syncs the
  repos, rediscovers plugins, and runs the due-check once in the background.

Each source's `next_check_at` (in the API/dashboard) reflects its schedule. For a
multi-instance deployment, set `PULSE_SCHEDULER_ENABLED=false` and drive
`POST /admin/refresh` centrally (e.g. AWS EventBridge Scheduler) so only one
sweep runs at a time.

## Quick start (local dev)

Development targets **free-threaded CPython 3.14 (`3.14t`)** via [`uv`](https://docs.astral.sh/uv/)
(pinned in `.python-version`):

```bash
uv venv --python 3.14t .venv
uv pip install --python .venv/bin/python -e ".[dev]"
source .venv/bin/activate

# Run the API (syncs repos + discovers plugins in the background on startup)
biothings-pulse serve --reload --port 8080
# dashboard: http://localhost:8080/   ·   API docs: http://localhost:8080/docs
```

> Prefer `biothings-pulse serve --reload` over a bare
> `uvicorn … --reload`: at runtime the app git-clones plugin repos and writes a
> SQLite DB into the cache dir, and uvicorn's default watcher would treat those
> as source changes and reload endlessly. The CLI scopes the reload watcher to
> the package source. If you must use uvicorn directly, do the same:
> `uvicorn biothings_pulse.main:app --reload --reload-dir src`.

> **BioThings SDK:** currently pinned to a specific commit of the
> `feature/asyncio-modernization` branch (see `pyproject.toml`) for reproducible
> installs. It swaps `orjson` for `msgspec`, which is free-threaded-safe, so the
> GIL stays disabled on `3.14t`. Revert to a released `biothings[hub]` once those
> changes ship to PyPI. (The code also runs on stable CPython 3.12 if needed.)
>
> Both local dev and the production Docker image run on free-threaded 3.14t
> (the image builds it via `uv`, since the official `python:*` images don't
> publish free-threaded slim variants).

Or use the CLI:

```bash
biothings-pulse list                       # discover + list all plugins
biothings-pulse check pending.api chebi    # check a single source (JSON)
biothings-pulse serve --reload             # run the API server
```

> First startup git-clones every configured repo. To iterate quickly, point
> `PULSE_REGISTRY_FILE` at a registry YAML with just one repo (see
> `src/biothings_pulse/data/default_repos.yaml` for the format).

## API

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /` | public | **Dashboard** — live pulse of all sources (links to `/docs`) |
| `GET /docs` | public | Interactive API documentation (OpenAPI/Swagger UI) |
| `GET /health` | public | Liveness + catalog size |
| `GET /catalog` | public | Discovered sources (no state) |
| `GET /sources` | public | All sources with last-known status |
| `GET /sources/{repo}/{plugin}` | public | Cached status; `?refresh=true` forces a check (**admin**) |
| `POST /sources/{repo}/{plugin}/check` | **admin** | Force a fresh check of one source |
| `POST /admin/sync` | **admin** | Re-pull repos & rediscover |
| `POST /admin/refresh` | **admin** | Check every source now |

Reads (`GET`) are **public and read-only** — they return the last cached result,
so consumers can poll freely; live checks happen on the scheduler, or via the
admin operations below.

### Admin auth
Mutating operations require a shared secret, **`PULSE_ADMIN_TOKEN`**:

- It **defaults to `"changeme"`** so admin mode works on a dev server out of the
  box — **set a real secret in production** (a warning is logged while the default
  is in use). Set it to an **empty** value to disable admin ops entirely
  (fully read-only).
- Send it as `Authorization: Bearer <token>` (or an `X-Admin-Token` header). The
  **dashboard** has an **“admin” button**: click it, paste the token (kept in the
  browser's `localStorage`), and the Re-check-all / Sync-repos / per-row re-check
  actions appear; otherwise they're hidden. `GET /health` reports
  `admin_enabled`.

```bash
curl -X POST localhost:8080/admin/refresh -H "Authorization: Bearer $PULSE_ADMIN_TOKEN"
```

For stronger protection, also front the service with your platform's auth (e.g.
an ALB/API-Gateway authorizer); the token is app-level defense-in-depth.

Example response:

```json
{
  "repo": "pending.api",
  "plugin": "chebi",
  "plugin_type": "manifest",
  "current_version": "2026-07-07",
  "current_version_at": "2026-07-08T02:00:00Z",
  "last_version": "2026-06-30",
  "last_version_at": "2026-07-01T02:00:00Z",
  "download_urls": ["http://purl.obolibrary.org/obo/chebi.obo"],
  "status": "ok",
  "error": null,
  "schedule": "0 1 * * 0",
  "checked_at": "2026-07-23T22:05:25Z",
  "next_check_at": "2026-07-26T01:00:00Z"
}
```

`status` is `ok` | `error` | `unsupported` | `pending`. Failures are isolated
per-source (a broken plugin never takes down the catalog).

## Configuration

All settings are env vars prefixed `PULSE_` (see `src/biothings_pulse/config.py`).

| Variable | Default | Notes |
|---|---|---|
| `PULSE_REGISTRY_FILE` | bundled `default_repos.yaml` | Repos to monitor |
| `PULSE_CACHE_DIR` | `.cache/repos` | Where repos are cloned |
| `PULSE_STORE_BACKEND` | `sqlite` | `sqlite` or `dynamodb` |
| `PULSE_SQLITE_PATH` | `.cache/pulse_state.db` | SQLite store path |
| `PULSE_DYNAMODB_TABLE` | `biothings-pulse-state` | DynamoDB table |
| `PULSE_DYNAMODB_ENDPOINT_URL` | – | e.g. `http://localhost:8000` for dynamodb-local |
| `PULSE_CHECK_TIMEOUT` | `60` | Per-check timeout (s) |
| `PULSE_SCHEDULER_ENABLED` | `true` | In-app due-based scheduler |
| `PULSE_SCHEDULER_INTERVAL` | `86400` | Default per-source cadence (s) when a plugin has no schedule |
| `PULSE_SCHEDULER_TICK` | `3600` | How often the scheduler evaluates due-ness (s) |
| `PULSE_SYNC_ON_STARTUP` | `true` | Sync + discover + initial due-check at boot |
| `PULSE_MAX_CHECK_WORKERS` | `8` | Check threadpool size |
| `PULSE_ADMIN_TOKEN` | `changeme` | Secret for admin ops (override in prod); empty = admin disabled (read-only) |

### Adding a new repo of plugins

The set of monitored repos lives in a **registry YAML**. The bundled default is
`src/biothings_pulse/data/default_repos.yaml` (it lists the standard BioThings
hubs). To add your own repo without editing the package, copy that file, add an
entry, and point `PULSE_REGISTRY_FILE` at your copy.

1. **Create/extend a registry file**, e.g. `my_registry.yaml`:

   ```yaml
   # Optional: override the glob patterns applied to every repo below.
   defaults:
     manifest_globs:
       - "plugins/*/manifest.json"
     advanced_globs:
       - "**/hub/dataload/sources/*"
       - "plugins/*"

   repos:
     - name: my-hub                                   # unique; used as {repo} in the API path
       git_url: https://github.com/biothings/my-hub.git
       ref: null                                      # branch/tag/commit; null = default branch
       enabled: true                                  # set false to keep but skip
       submodules: ["plugins"]                        # false | true | list of path prefixes
       # Per-repo overrides (optional; fall back to `defaults` above):
       # manifest_globs: ["plugins/*/manifest.json"]
       # advanced_globs: ["**/hub/dataload/sources/*", "plugins/*"]
   ```

   Field reference:
   - **`name`** — unique short name; it becomes the `{repo}` segment in
     `GET /sources/{repo}/{plugin}`.
   - **`git_url`** — HTTPS clone URL.
   - **`ref`** — branch, tag, or commit to check out; `null` uses the remote's
     default branch.
   - **`submodules`** — `false` (none), `true` (all), or a list of path prefixes
     to initialise (e.g. `["plugins"]` fetches plugin submodules while skipping
     large top-level hub mirrors). Needed for repos like `pending.api` whose
     plugins are submodules.
   - **`manifest_globs` / `advanced_globs`** — where to look for plugins,
     relative to the repo root. Defaults cover the conventional BioThings layout,
     so most repos need no override. Manifest plugins are matched by their
     `manifest.json`; advanced plugins by a source directory containing a
     `*dump*.py` module. A manifest and an advanced match with the same name →
     the manifest wins.

2. **Point Pulse at it and reload the catalog:**

   ```bash
   export PULSE_REGISTRY_FILE=/path/to/my_registry.yaml
   # then either restart the server, or (while it's running) reload live:
   curl -X POST localhost:8080/admin/sync
   ```

   `admin/sync` re-clones/pulls every repo and rediscovers plugins. Confirm with
   `GET /catalog` (or `biothings-pulse list`). A repo that fails to clone is
   logged and skipped — it won't break discovery of the others.

> A repo does **not** have to be a full Hub — a repo containing only a `plugins/`
> directory (or only advanced `hub/dataload/sources/`) works too.

**Plugin pip requirements.** Plugins may declare `requires` (manifest) or ship a
`requirements.txt` (advanced). Pre-install them so checks never install anything
at request time (also wired into the Docker build via
`--build-arg PREINSTALL_PLUGIN_REQUIRES=true`):

```bash
python scripts/install_plugin_requires.py          # sync + install
python scripts/install_plugin_requires.py --print  # just list them
```

## Docker

```bash
docker build -f deploy/Dockerfile -t biothings-pulse .
docker run -p 8080:8080 -v pulse-data:/data biothings-pulse
# or:
docker compose -f deploy/docker-compose.yml up --build
```

Build with `--build-arg PREINSTALL_PLUGIN_REQUIRES=true` to bake plugin deps in.

## AWS deployment (ECS Fargate + Terraform)

`deploy/terraform/` provisions ECR, a DynamoDB state table, an ECS Fargate
service behind an ALB, CloudWatch logs, and IAM roles (uses the default VPC
unless overridden).

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars   # edit as needed
terraform init
terraform apply                                # creates ECR (among others)

# Build & push the image to the new ECR repo, then re-apply:
ECR=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password | docker login --username AWS --password-stdin "${ECR%/*}"
docker build -f ../Dockerfile -t "$ECR:latest" ../..
docker push "$ECR:latest"
terraform apply                                # rolls out the service

curl "http://$(terraform output -raw alb_dns_name)/health"
```

The state store is DynamoDB and the in-app scheduler refreshes on an interval.
To scale beyond one task, set `scheduler_enabled = false` and drive
`POST /admin/refresh` centrally (e.g. EventBridge Scheduler — hook noted in
`main.tf`).

## Development

```bash
pytest                 # unit tests (fast, no network)
pytest -m integration  # opt-in: clones pending.api and checks a real source
ruff check src tests
```

## Project layout

```
src/biothings_pulse/
  config.py         settings + repo registry
  bootstrap.py      initialise the BioThings SDK standalone (config shim)
  hub_config.py     SQLite-backed BioThings config module
  plugins/          git sync + plugin discovery + requirements
  checker/          load a plugin's dumper + run release detection only
  store/            SourceState + SQLite / DynamoDB backends
  service.py        catalog + check orchestration + persistence
  scheduler.py      periodic refresh
  api/              FastAPI routes + schemas
  main.py           app factory + lifespan
deploy/             Dockerfile, docker-compose, Terraform
```

See `INSTRUCTIONS.md` for the original project brief.
