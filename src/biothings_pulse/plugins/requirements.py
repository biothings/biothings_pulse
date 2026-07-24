"""Collect third-party pip requirements declared by plugins and their repos.

Used at build/sync time (see ``scripts/install_plugin_requires.py``) to
pre-install everything checks might import, so the check step never has to
install anything at request time.

Requirements come from three places:
  * manifest ``requires`` (manifest plugins);
  * a ``requirements*.txt`` next to an advanced plugin;
  * repo-level config in the registry — each repo's ``requirements`` (inline
    packages) and ``requirements_files`` (repo-relative files), e.g. to declare
    the ``lxml``/``pandas``/``bitarray`` that some hubs' dumpers import.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Dict, List, Set

from ..config import RepoSpec
from .models import PluginRef

logger = logging.getLogger(__name__)

# Never (re)install the SDK itself from a plugin repo's pins — Pulse controls the
# biothings version (currently a pinned git branch) via its own dependencies.
_SKIP_PREFIXES = ("biothings",)

_PLUGIN_REQ_FILES = ("requirements.txt", "requirements-hub.txt", "requirements_hub.txt")

# Standard-library module names (empty on <3.10, where filtering is skipped).
_STDLIB = getattr(sys, "stdlib_module_names", frozenset())


def _dist_name(req: str) -> str:
    """The distribution/package name from a requirement line (drop version/extras)."""
    return re.split(r"[<>=!~;\[\s]", req, maxsplit=1)[0].strip()


def _drop_stdlib(reqs: Iterable[str]) -> List[str]:
    """Drop requirements that are actually stdlib modules (e.g. asyncio, tarfile)
    — installing those from PyPI is wrong/harmful — and warn about each."""
    kept, dropped = [], []
    for r in reqs:
        if _dist_name(r).replace("-", "_").lower() in _STDLIB:
            dropped.append(r)
        else:
            kept.append(r)
    if dropped:
        logger.warning(
            "Ignoring stdlib module(s) listed as plugin requirements: %s",
            ", ".join(sorted(set(dropped))),
        )
    return kept


def _parse_req_file(path: Path) -> List[str]:
    reqs: List[str] = []
    try:
        text = path.read_text()
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return reqs
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # skip blanks, comments, -r/-e/--flags
            continue
        if line.lower().startswith(_SKIP_PREFIXES):
            continue
        reqs.append(line)
    return reqs


def _manifest_requires(manifest_path: Path) -> List[str]:
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not parse %s: %s", manifest_path, exc)
        return []
    req = manifest.get("requires") or []
    if isinstance(req, str):
        req = [req]
    out = []
    for r in req:
        r = str(r).strip()
        if r and not r.lower().startswith(_SKIP_PREFIXES):
            out.append(r)
    return out


def _files_in(directory: Path, names) -> List[str]:
    reqs: List[str] = []
    for name in names:
        rf = directory / name
        if rf.exists():
            reqs.extend(_parse_req_file(rf))
    return reqs


def collect_requirements(refs: Iterable[PluginRef]) -> List[str]:
    """Per-plugin requirements (manifest ``requires`` + advanced req files)."""
    out: Set[str] = set()
    for ref in refs:
        if ref.plugin_type == "manifest" and ref.manifest_path:
            out.update(_manifest_requires(ref.manifest_path))
        elif ref.plugin_type == "advanced":
            out.update(_files_in(ref.path, _PLUGIN_REQ_FILES))
    return sorted(_drop_stdlib(out))


def _clean(reqs: Iterable[str]) -> List[str]:
    out = []
    for r in reqs:
        r = str(r).strip()
        if r and not r.startswith("-") and not r.lower().startswith(_SKIP_PREFIXES):
            out.append(r)
    return out


def collect_repo_requirements(
    repos: Iterable[RepoSpec], paths: Dict[str, Path]
) -> List[str]:
    """Repo-declared requirements: each spec's inline ``requirements`` plus any
    ``requirements_files`` (resolved relative to that repo's checkout)."""
    out: Set[str] = set()
    for spec in repos:
        out.update(_clean(spec.requirements))
        repo_path = paths.get(spec.name)
        if repo_path is not None:
            out.update(_files_in(Path(repo_path), spec.requirements_files))
    return sorted(_drop_stdlib(out))
