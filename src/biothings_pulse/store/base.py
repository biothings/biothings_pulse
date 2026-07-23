"""State store interface and the per-source state record."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceState(BaseModel):
    """Everything BioThings Pulse knows about one data source.

    ``current_version`` is Pulse's own source of truth for "what is deployed /
    acknowledged". ``latest_version`` is what the most recent check detected on
    the remote. ``has_update`` compares the two.
    """

    repo: str
    plugin: str
    plugin_type: str = "unknown"  # "manifest" | "advanced" | "unknown"

    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    download_urls: List[str] = Field(default_factory=list)

    status: str = "pending"  # "pending" | "ok" | "error" | "unsupported"
    error: Optional[str] = None

    checked_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=_now)

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.plugin}"

    @property
    def has_update(self) -> bool:
        """True when a latest version is known and differs from the baseline.

        A source that has never been baselined (``current_version is None``)
        reports ``False`` — the first successful check adopts the detected
        version as the baseline (see :meth:`StateStore.record_check`).
        """
        return (
            self.current_version is not None
            and self.latest_version is not None
            and self.latest_version != self.current_version
        )

    def is_stale(self, ttl_seconds: float) -> bool:
        if self.checked_at is None:
            return True
        age = (_now() - self.checked_at).total_seconds()
        return age > ttl_seconds


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
        latest_version: Optional[str],
        download_urls: Optional[List[str]] = None,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> SourceState:
        """Persist the outcome of a check and return the updated state.

        On the *first* successful check for a source, the detected version is
        adopted as the baseline ``current_version`` so it does not immediately
        read as "has update".
        """
        state = self.get(repo, plugin) or SourceState(
            repo=repo, plugin=plugin, plugin_type=plugin_type
        )
        state.plugin_type = plugin_type or state.plugin_type
        state.status = status
        state.error = error
        state.updated_at = _now()

        if status == "ok":
            state.latest_version = latest_version
            state.download_urls = download_urls or []
            state.checked_at = _now()
            if state.current_version is None and latest_version is not None:
                # Establish baseline on first successful observation.
                state.current_version = latest_version

        self.put(state)
        return state

    def acknowledge(self, repo: str, plugin: str) -> Optional[SourceState]:
        """Advance the baseline: set ``current_version = latest_version``."""
        state = self.get(repo, plugin)
        if state is None:
            return None
        state.current_version = state.latest_version
        state.updated_at = _now()
        self.put(state)
        return state
