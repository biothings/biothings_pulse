#!/usr/bin/env python
"""Discover all plugins and install their declared requirements.

Run at image build time (or once after deploy) so the in-process check step
never has to install anything at request time. Requirements come from the
registry's inline repo ``requirements`` (e.g. lxml/pandas/bitarray), manifest
``requires``, and advanced-plugin ``requirements.txt`` files.

Installs with ``uv pip`` when available (the production image's venv has no
``pip``), falling back to ``python -m pip`` otherwise.

Usage:
    python scripts/install_plugin_requires.py               # sync, then install
    python scripts/install_plugin_requires.py --print       # just list them
    python scripts/install_plugin_requires.py --no-sync     # use existing cache
    python scripts/install_plugin_requires.py --config-only # only the registry's
        # inline repo requirements (lxml/pandas/bitarray, ...); no git sync
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys

from biothings_pulse.config import get_settings
from biothings_pulse.plugins.discovery import discover_plugins
from biothings_pulse.plugins.requirements import (
    collect_repo_requirements,
    collect_requirements,
)
from biothings_pulse.plugins.sync import sync_registry


def _install_cmd(requirements: list[str]) -> list[str]:
    """Prefer uv (the image venv has no pip); fall back to pip."""
    if shutil.which("uv"):
        return ["uv", "pip", "install", *requirements]
    return [sys.executable, "-m", "pip", "install", *requirements]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", help="Only print requirements")
    parser.add_argument("--no-sync", action="store_true", help="Skip git sync")
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Only the registry's inline repo requirements; no sync/discovery.",
    )
    args = parser.parse_args()

    settings = get_settings()
    registry = settings.load_registry()
    repos = registry.resolved_repos()

    if args.config_only:
        # Registry-declared inline requirements need no checkout, so skip both the
        # git sync and plugin discovery — fast and network-light for image builds.
        requirements = collect_repo_requirements(repos, {})
    else:
        if args.no_sync:
            paths = {
                spec.name: settings.cache_dir / spec.name
                for spec in repos
                if (settings.cache_dir / spec.name).exists()
            }
        else:
            paths = sync_registry(repos, settings)

        refs = []
        for spec in repos:
            path = paths.get(spec.name)
            if path:
                refs.extend(discover_plugins(spec.name, path, spec))

        requirements = sorted(
            set(collect_requirements(refs)) | set(collect_repo_requirements(repos, paths))
        )

    print(f"# {len(requirements)} plugin/hub requirement(s) discovered:")
    for req in requirements:
        print(req)

    if args.print or not requirements:
        return 0

    cmd = _install_cmd(requirements)
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
