"""State store interface and the per-source state record."""

from __future__ import annotations

import abc
import logging
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceState(BaseModel):
    """What BioThings Pulse has observed about one data source.

    Pulse only reports upstream facts; it does not track whether any particular
    consumer has "updated". Downstream hubs/apps poll the API and maintain their
    own update state by comparing ``current_version`` against what they deployed.

    ``current_version`` is the most recently detected upstream version and
    ``current_version_at`` is when it was *first* seen. When a check detects a
    different version, the previous one is retained as ``last_version`` /
    ``last_version_at``.
    """

    repo: str
    plugin: str
    plugin_type: str = "unknown"  # "manifest" | "advanced" | "unknown"

    current_version: Optional[str] = None
    current_version_at: Optional[datetime] = None
    last_version: Optional[str] = None
    last_version_at: Optional[datetime] = None
    download_urls: List[str] = Field(default_factory=list)

    schedule: Optional[str] = None
    """The plugin's own check schedule (cron). None -> Pulse default interval."""

    status: str = "pending"  # "pending" | "ok" | "error" | "unsupported"
    error: Optional[str] = None

    checked_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=_now)

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.plugin}"


def deserialize_state(doc: str) -> Optional[SourceState]:
    """Parse a stored record JSON, skipping (with a warning) any that no longer
    validate — one legacy/corrupt row must not break the whole listing."""
    try:
        return SourceState.model_validate_json(doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Skipping unreadable state record: %s", exc)
        return None


class StateStore(abc.ABC):
    """Backend-agnostic persistence for :class:`SourceState` records."""

    @abc.abstractmethod
    def get(self, repo: str, plugin: str) -> Optional[SourceState]:
        ...

    @abc.abstractmethod
    def put(self, state: SourceState) -> None:
        ...

    @abc.abstractmethod
    def list_all(self) -> List[SourceState]:
        ...

    # -- higher-level operations (shared logic) ---------------------------

    def record_check(
        self,
        repo: str,
        plugin: str,
        plugin_type: str,
        *,
        detected_version: Optional[str],
        download_urls: Optional[List[str]] = None,
        status: str = "ok",
        error: Optional[str] = None,
        schedule: Optional[str] = None,
    ) -> SourceState:
        """Persist the outcome of a check and return the updated state.

        On a successful check, if the detected version differs from the stored
        ``current_version`` (including the very first sighting), the current
        version is rotated into ``last_version`` and the new one is recorded with
        ``current_version_at = now``. An unchanged version leaves the timestamps
        intact, so ``current_version_at`` always reflects when that version was
        *first* seen.
        """
        now = _now()
        state = self.get(repo, plugin) or SourceState(
            repo=repo, plugin=plugin, plugin_type=plugin_type
        )
        state.plugin_type = plugin_type or state.plugin_type
        state.status = status
        state.error = error
        state.updated_at = now
        state.checked_at = now  # every attempt, success or failure

        # Only trust the schedule when the plugin actually loaded (ok/unsupported);
        # a transient error shouldn't wipe a previously-known schedule.
        if status in ("ok", "unsupported"):
            state.schedule = schedule

        if status == "ok":
            # Coerce to str: some dumpers put non-string values in to_dump
            # (e.g. civic uses int variant IDs), which must not break storage.
            state.download_urls = [str(u) for u in (download_urls or [])]
            if detected_version is not None and detected_version != state.current_version:
                # New version (or first sighting): rotate current -> last.
                if state.current_version is not None:
                    state.last_version = state.current_version
                    state.last_version_at = state.current_version_at
                state.current_version = detected_version
                state.current_version_at = now

        self.put(state)
        return state
