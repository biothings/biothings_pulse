"""Collect third-party pip requirements declared by plugins and their repos.

Used at build/sync time (see ``scripts/install_plugin_requires.py``) to
pre-install everything checks might import, so the check step never has to
install anything at request time.

Requirements come from three places:
  * manifest ``requires`` (manifest plugins);
  * a ``requirements*.txt`` next to an advanced plugin;
  * the repo-root ``requirements_hub.txt`` — where the BioThings hubs actually
    declare hub-side deps like ``lxml``/``pandas``/``bitarray`` that advanced
    dumpers import.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import List, Set

from .models import PluginRef

logger = logging.getLogger(__name__)

# Never (re)install the SDK itself from a plugin repo's pins — Pulse controls the
# biothings version (currently a pinned git branch) via its own dependencies.
_SKIP_PREFIXES = ("biothings",)

_PLUGIN_REQ_FILES = ("requirements.txt", "requirements-hub.txt", "requirements_hub.txt")
_REPO_REQ_FILES = ("requirements_hub.txt", "requirements-hub.txt")


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
    return sorted(out)


def collect_repo_requirements(repo_paths: Iterable[Path]) -> List[str]:
    """Hub-side requirements declared at each repo root (``requirements_hub.txt``)."""
    out: Set[str] = set()
    for path in repo_paths:
        out.update(_files_in(Path(path), _REPO_REQ_FILES))
    return sorted(out)
