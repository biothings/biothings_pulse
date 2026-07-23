"""Collect third-party pip requirements declared by plugins.

Used at build/sync time (see ``scripts/install_plugin_requires.py``) to
pre-install everything checks might import, so the check step never has to
install anything at request time.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import List, Set

from .models import PluginRef

logger = logging.getLogger(__name__)


def _manifest_requires(manifest_path: Path) -> List[str]:
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not parse %s: %s", manifest_path, exc)
        return []
    req = manifest.get("requires") or []
    if isinstance(req, str):
        req = [req]
    return [str(r).strip() for r in req if str(r).strip()]


def _advanced_requires(plugin_dir: Path) -> List[str]:
    reqs: List[str] = []
    for name in ("requirements.txt", "requirements-hub.txt"):
        rf = plugin_dir / name
        if rf.exists():
            for line in rf.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if line and not line.startswith("-"):
                    reqs.append(line)
    return reqs


def collect_requirements(refs: Iterable[PluginRef]) -> List[str]:
    """Return the de-duplicated union of requirements across all plugins."""
    out: Set[str] = set()
    for ref in refs:
        if ref.plugin_type == "manifest" and ref.manifest_path:
            out.update(_manifest_requires(ref.manifest_path))
        elif ref.plugin_type == "advanced":
            out.update(_advanced_requires(ref.path))
    return sorted(out)
