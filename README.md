# BioThings Pulse

A standalone, production-ready API server that runs **only the data-source-check
step** of a [BioThings Hub](https://docs.biothings.io) data plugin — without
standing up a full Hub — and reports, per source:

1. **Is there a new data update?** (`has_update`)
2. **What is the current version?** (as tracked by Pulse — `current_version`)
3. **If updated, what is the latest version?** (`latest_version`)
4. *(Optional)* the list of **download URLs** the plugin would fetch.

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
3. **Read the result.** `latest_version` = `dumper.release`; `download_urls` =
   the remote URLs the dumper queued in `dumper.to_dump`.

**Deciding `has_update`.** Pulse's own state store — **not** a live API or the
Hub DB — is the source of truth for `current_version`:

- The **first** successful check adopts the detected version as the baseline
  (`current_version = latest_version`, so `has_update` is `false`).
- Afterwards, `has_update` is `true` whenever a check finds
  `latest_version != current_version`.
- `POST /sources/{repo}/{plugin}/acknowledge` advances the baseline to the
  latest — e.g. after the source has actually been ingested downstream — so the
  flag clears until the next new release.

Each check is isolated: a failing or uncheckable plugin is recorded with
`status: error` / `unsupported` and never affects other sources. Results are
persisted to the state store (SQLite locally, DynamoDB on AWS).

## How often it refreshes

Checks are cheap (a few HTTP `HEAD`s, no downloads), but Pulse still avoids
hammering upstream servers by caching results and refreshing on three triggers:

- **On demand.** `GET /sources/{repo}/{plugin}` returns the cached status, and
  re-checks transparently only if there is no result yet or the cached one is
  **older than `PULSE_CHECK_TTL`** (default **3600 s / 1 h**).
  `POST /sources/{repo}/{plugin}/check` always forces an immediate fresh check,
  ignoring the cache.
- **On a schedule.** When `PULSE_SCHEDULER_ENABLED=true` (the default), an
  in-process scheduler sweeps **every source** every `PULSE_SCHEDULER_INTERVAL`
  seconds (default **86400 s / daily**, which is enough for most data sources).
  `POST /admin/refresh` runs that sweep
  on demand.
- **On startup.** If `PULSE_SYNC_ON_STARTUP=true` (default), Pulse git-syncs the
  repos and rediscovers plugins in the background as it boots.

Tune the cadence with `PULSE_SCHEDULER_INTERVAL` and `PULSE_CHECK_TTL`. For a
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

| Method & path | Purpose |
|---|---|
| `GET /` | **Dashboard** — live pulse of all sources (links to `/docs`) |
| `GET /docs` | Interactive API documentation (OpenAPI/Swagger UI) |
| `GET /health` | Liveness + catalog size |
| `GET /catalog` | Discovered sources (no state) |
| `GET /sources` | All sources with last-known status |
| `GET /sources/{repo}/{plugin}` | Status; `?refresh=true` forces a check |
| `POST /sources/{repo}/{plugin}/check` | Force a fresh check |
| `POST /sources/{repo}/{plugin}/acknowledge` | Advance the tracked `current_version` |
| `POST /admin/sync` | Re-pull repos & rediscover |
| `POST /admin/refresh` | Check every source now |

Example response:

```json
{
  "repo": "pending.api",
  "plugin": "chebi",
  "plugin_type": "manifest",
  "has_update": true,
  "current_version": "2024-01-01",
  "latest_version": "2026-07-07",
  "download_urls": ["http://purl.obolibrary.org/obo/chebi.obo"],
  "status": "ok",
  "error": null,
  "checked_at": "2026-07-23T22:05:25Z"
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
| `PULSE_CHECK_TTL` | `3600` | Cached result freshness (s) |
| `PULSE_SCHEDULER_ENABLED` | `true` | In-app periodic refresh |
| `PULSE_SCHEDULER_INTERVAL` | `86400` | Refresh interval (s, default daily) |
| `PULSE_SYNC_ON_STARTUP` | `true` | Sync + discover at boot |
| `PULSE_MAX_CHECK_WORKERS` | `8` | Check threadpool size |

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
