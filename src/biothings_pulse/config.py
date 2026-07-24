"""Runtime configuration for BioThings Pulse.

All settings are environment-driven (prefix ``PULSE_``) via pydantic-settings,
so the same image runs locally (SQLite + local git cache) or on AWS (DynamoDB)
by changing env vars only.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DATA_DIR = Path(__file__).parent / "data"
_DEFAULT_REGISTRY_FILE = _DATA_DIR / "default_repos.yaml"


class RepoSpec(BaseModel):
    """A single Hub repository to monitor."""

    name: str
    git_url: str
    ref: Optional[str] = None
    enabled: bool = True
    manifest_globs: List[str] = Field(default_factory=list)
    advanced_globs: List[str] = Field(default_factory=list)
    submodules: Union[bool, List[str]] = False
    """Initialise git submodules after clone/pull. ``True`` = all; a list = only
    submodule paths under those prefixes (e.g. ``["plugins"]`` skips large
    top-level hub mirrors); ``False`` = none."""


class Registry(BaseModel):
    """The full set of monitored repositories plus default glob patterns."""

    manifest_globs: List[str] = Field(
        default_factory=lambda: [
            "plugins/*/manifest.json",
            "src/plugins/*/manifest.json",
        ]
    )
    advanced_globs: List[str] = Field(
        default_factory=lambda: [
            "**/hub/dataload/sources/*",
            "plugins/*",
            "src/plugins/*",
        ]
    )
    repos: List[RepoSpec] = Field(default_factory=list)

    def resolved_repos(self) -> List[RepoSpec]:
        """Return enabled repos with per-repo globs filled in from defaults."""
        out: List[RepoSpec] = []
        for repo in self.repos:
            if not repo.enabled:
                continue
            out.append(
                repo.model_copy(
                    update={
                        "manifest_globs": repo.manifest_globs or self.manifest_globs,
                        "advanced_globs": repo.advanced_globs or self.advanced_globs,
                    }
                )
            )
        return out


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_prefix="PULSE_", env_file=".env", extra="ignore"
    )

    # --- Plugin sourcing -------------------------------------------------
    registry_file: Optional[Path] = None
    """Override path to a registry YAML. Defaults to the bundled default_repos.yaml."""

    cache_dir: Path = Path(".cache/repos")
    """Where monitored repos are git-cloned."""

    git_clone_depth: int = 1
    """Shallow-clone depth (1 = latest commit only)."""

    sync_on_startup: bool = True
    """Clone/pull all repos when the app starts."""

    # --- Check behaviour -------------------------------------------------
    check_timeout: float = 60.0
    """Per-source check timeout, in seconds."""

    max_check_workers: int = 8
    """Size of the threadpool that runs (blocking) plugin checks."""

    data_archive_root: Optional[Path] = None
    """Scratch dir passed to the biothings config shim. Defaults to a temp dir."""

    # --- Scheduler -------------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_interval: float = 86400.0
    """Default per-source check cadence (seconds) for sources without their own
    schedule (default: daily)."""

    scheduler_tick: float = 3600.0
    """How often the scheduler wakes to check which sources are due (seconds).
    Should be <= the finest plugin cron granularity you care about (default: hourly)."""

    # --- State store -----------------------------------------------------
    store_backend: str = "sqlite"
    """One of: 'sqlite' (local dev) or 'dynamodb' (AWS)."""

    sqlite_path: Path = Path(".cache/pulse_state.db")
    dynamodb_table: str = "biothings-pulse-state"
    dynamodb_endpoint_url: Optional[str] = None
    """Set to e.g. http://localhost:8000 to target dynamodb-local."""

    aws_region: str = "us-west-2"

    # --- Server ----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"

    admin_token: Optional[str] = None
    """Shared secret for admin/mutating operations (sync, refresh, force-check).
    Unset => those operations are disabled (the API/dashboard are read-only).
    When set, clients must send it as `Authorization: Bearer <token>` (or the
    `X-Admin-Token` header)."""

    def load_registry(self) -> Registry:
        path = self.registry_file or _DEFAULT_REGISTRY_FILE
        return load_registry(path)


def load_registry(path: Path) -> Registry:
    """Parse a registry YAML file into a :class:`Registry`."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    defaults = raw.get("defaults") or {}
    return Registry(
        manifest_globs=defaults.get("manifest_globs")
        or ["plugins/*/manifest.json", "src/plugins/*/manifest.json"],
        advanced_globs=defaults.get("advanced_globs")
        or ["**/hub/dataload/sources/*", "plugins/*", "src/plugins/*"],
        repos=[RepoSpec(**r) for r in (raw.get("repos") or [])],
    )


@functools.lru_cache
def get_settings() -> Settings:
    """Cached application settings (safe to import anywhere)."""
    return Settings()
