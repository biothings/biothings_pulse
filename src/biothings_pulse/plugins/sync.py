"""Git-sync monitored repositories into the local cache directory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from git import Repo

from ..config import RepoSpec, Settings

logger = logging.getLogger(__name__)


def sync_repo(spec: RepoSpec, cache_dir: Path, depth: int = 1) -> Path:
    """Clone ``spec`` into ``cache_dir`` (or fetch+reset if already present).

    Returns the local checkout path. Raises on unrecoverable git errors.
    """
    dest = Path(cache_dir) / spec.name
    dest.parent.mkdir(parents=True, exist_ok=True)

    if (dest / ".git").exists():
        logger.info("Updating repo %s at %s", spec.name, dest)
        repo = Repo(str(dest))
        origin = repo.remotes.origin
        origin.fetch(depth=depth) if depth else origin.fetch()
        target = spec.ref or _default_branch(repo)
        repo.git.reset("--hard", f"origin/{target}")
    else:
        logger.info("Cloning %s -> %s", spec.git_url, dest)
        clone_kwargs: dict = {}
        if depth:
            clone_kwargs["depth"] = depth
        if spec.ref:
            clone_kwargs["branch"] = spec.ref
        repo = Repo.clone_from(spec.git_url, str(dest), **clone_kwargs)

    _update_submodules(repo, spec, depth)
    return dest


def _update_submodules(repo: Repo, spec: RepoSpec, depth: int) -> None:
    """Init/update submodules per the repo spec.

    ``spec.submodules`` is ``False`` (skip), ``True`` (all), or a list of path
    prefixes to limit which submodules are fetched (keeps large top-level hub
    mirrors out).
    """
    if not spec.submodules:
        return
    args = ["update", "--init"]
    if depth:
        args += ["--depth", str(depth)]
    paths: List[str] = []
    if isinstance(spec.submodules, list):
        paths = spec.submodules
    try:
        repo.git.submodule(*args, "--", *paths) if paths else repo.git.submodule(*args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("submodule init failed for %s: %s", spec.name, exc)


def _default_branch(repo: Repo) -> str:
    try:
        ref = repo.remotes.origin.refs["HEAD"].reference.name
        return ref.split("/")[-1]
    except Exception:
        # Fall back to the currently checked-out branch name.
        try:
            return repo.active_branch.name
        except Exception:
            return "master"


def sync_registry(
    repos: List[RepoSpec], settings: Settings
) -> Dict[str, Path]:
    """Sync all repos; return ``{repo_name: local_path}`` for those that succeed.

    A failure on one repo is logged and skipped so a single unreachable repo
    doesn't take down the whole catalog.
    """
    result: Dict[str, Path] = {}
    for spec in repos:
        try:
            result[spec.name] = sync_repo(
                spec, settings.cache_dir, depth=settings.git_clone_depth
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to sync repo %s: %s", spec.name, exc)
    return result
