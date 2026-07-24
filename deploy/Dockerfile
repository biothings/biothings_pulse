# BioThings Pulse production image.
# Build from the repo root:  docker build -f deploy/Dockerfile -t biothings-pulse .
#
# Runs on free-threaded CPython 3.14 (3.14t), installed via uv (the official
# python:* images don't publish free-threaded slim variants). The BioThings SDK
# is installed from a pinned git commit (see pyproject.toml) — hence `git`.
FROM debian:bookworm-slim AS base

# uv provides the free-threaded interpreter and the installer.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# git: install the pinned biothings SDK commit + clone/sync plugin repos at
# runtime (GitPython shells out). ca-certificates for HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PULSE_CACHE_DIR=/data/repos \
    PULSE_SQLITE_PATH=/data/pulse_state.db \
    PULSE_HUB_ROOT=/tmp/biothings_pulse \
    PULSE_HOST=0.0.0.0 \
    PULSE_PORT=8080

WORKDIR /app

# Free-threaded 3.14t venv on PATH (so `python`/`uvicorn` resolve to it).
RUN uv venv --python 3.14t "$VIRTUAL_ENV"

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install ".[aws]"

COPY scripts ./scripts

# Optionally pre-install every plugin's declared requirements at build time so
# checks never install anything at runtime. Off by default (keeps the image
# lean and the build offline-friendly). Enable with:
#   docker build --build-arg PREINSTALL_PLUGIN_REQUIRES=true ...
ARG PREINSTALL_PLUGIN_REQUIRES=false
RUN if [ "$PREINSTALL_PLUGIN_REQUIRES" = "true" ]; then \
        python scripts/install_plugin_requires.py || echo "plugin requires install: partial"; \
    fi

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
        sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PULSE_PORT','8080')+'/api/health').status==200 else sys.exit(1)"

CMD ["uvicorn", "biothings_pulse.main:app", "--host", "0.0.0.0", "--port", "8080"]
