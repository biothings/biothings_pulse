"""Discover manifest-based and advanced plugins within a synced repo."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from ..config import RepoSpec
from .models import PluginRef

logger = logging.getLogger(__name__)


def _git_web_url(git_url: str) -> Optional[str]:
    """Normalise a git clone URL to a browsable web URL."""
    u = (git_url or "").strip()
    if u.startswith("git+"):
        u = u[4:]
    if u.startswith("git@") and ":" in u:  # git@host:owner/repo(.git)
        host, path = u[4:].split(":", 1)
        u = f"https://{host}/{path}"
    if u.endswith(".git"):
        u = u[:-4]
    return u.rstrip("/") or None


def _source_url(spec: RepoSpec, repo_path: Path, plugin_dir: Path) -> Optional[str]:
    """Web link to a plugin's source directory within its repo."""
    web = _git_web_url(spec.git_url)
    if not web:
        return None
    try:
        rel = Path(plugin_dir).resolve().relative_to(Path(repo_path).resolve()).as_posix()
    except ValueError:
        rel = ""
    # GitHub uses /tree/<ref>/<path>; for other hosts just link to the repo root.
    if urlsplit(web).netloc == "github.com" and rel:
        return f"{web}/tree/{spec.ref or 'HEAD'}/{rel}"
    return web


def _looks_like_advanced_plugin(path: Path) -> bool:
    """A source package dir that plausibly contains a dumper.

    Heuristic (no imports): a ``*dump*.py`` module, or an ``__init__.py`` that
    references a dumper. This deliberately excludes manifest plugin dirs (which
    carry ``parser.py``/``manifest.json`` but no dumper module).
    """
    if not path.is_dir() or path.name.startswith((".", "__")):
        return False
    pyfiles = list(path.glob("*.py"))
    if not pyfiles:
        return False
    if any("dump" in p.stem.lower() for p in pyfiles):
        return True
    init = path / "__init__.py"
    if init.exists():
        try:
            return "dump" in init.read_text(errors="ignore").lower()
        except OSError:
            return False
    return False


def discover_plugins(
    repo_name: str, repo_path: Path, spec: RepoSpec
) -> List[PluginRef]:
    """Return all plugins found under ``repo_path`` per the repo's globs."""
    repo_path = Path(repo_path)
    seen: set[tuple[str, str]] = set()
    manifest_names: set[str] = set()
    refs: List[PluginRef] = []

    # Repo-configured extra sys.path dirs (resolved to existing absolute dirs).
    extra_sys_path = [
        d for p in spec.sys_path if (d := (repo_path / p)).is_dir()
    ]

    # --- manifest-based plugins -----------------------------------------
    for pattern in spec.manifest_globs:
        for mpath in sorted(repo_path.glob(pattern)):
            if not (mpath.is_file() and mpath.name == "manifest.json"):
                continue
            plugin_dir = mpath.parent
            key = (plugin_dir.name, "manifest")
            if key in seen:
                continue
            seen.add(key)
            manifest_names.add(plugin_dir.name)
            refs.append(
                PluginRef(
                    repo=repo_name,
                    name=plugin_dir.name,
                    plugin_type="manifest",
                    path=plugin_dir,
                    manifest_path=mpath,
                    repo_path=repo_path,
                    source_url=_source_url(spec, repo_path, plugin_dir),
                    extra_sys_path=extra_sys_path,
                )
            )

    # --- advanced plugins -----------------------------------------------
    for pattern in spec.advanced_globs:
        for spath in sorted(repo_path.glob(pattern)):
            if not _looks_like_advanced_plugin(spath):
                continue
            if spath.name in manifest_names:
                continue  # a manifest plugin of the same name wins
            key = (spath.name, "advanced")
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                PluginRef(
                    repo=repo_name,
                    name=spath.name,
                    plugin_type="advanced",
                    path=spath,
                    repo_path=repo_path,
                    source_url=_source_url(spec, repo_path, spath),
                    extra_sys_path=extra_sys_path,
                )
            )

    logger.info(
        "Discovered %d plugins in %s (%d manifest, %d advanced)",
        len(refs),
        repo_name,
        sum(1 for r in refs if r.plugin_type == "manifest"),
        sum(1 for r in refs if r.plugin_type == "advanced"),
    )
    return refs
