"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ..store.base import SourceState


class SourceStatus(BaseModel):
    """The core per-source status payload.

    Pulse reports only what it observed upstream; consumers compare
    ``current_version`` against their own deployed version to decide whether they
    need to update.
    """

    repo: str
    plugin: str
    plugin_type: str
    source_url: Optional[str] = Field(
        None, description="Web link to the plugin's source code."
    )
    current_version: Optional[str] = Field(
        None, description="Most recently detected upstream version."
    )
    current_version_at: Optional[datetime] = Field(
        None, description="When current_version was first detected."
    )
    last_version: Optional[str] = Field(
        None, description="Previously detected version, before current_version."
    )
    last_version_at: Optional[datetime] = Field(
        None, description="When last_version was first detected."
    )
    download_urls: List[str] = Field(
        default_factory=list, description="URLs the plugin would download."
    )
    status: str = Field(description="ok | error | unsupported | pending")
    error: Optional[str] = None
    schedule: Optional[str] = Field(
        None, description="Plugin's own check schedule (cron); null = Pulse default."
    )
    checked_at: Optional[datetime] = Field(
        None, description="When this source was last checked."
    )
    next_check_at: Optional[datetime] = Field(
        None, description="When the next scheduled check is due."
    )
    updated_at: Optional[datetime] = None

    @classmethod
    def from_state(cls, state: SourceState) -> SourceStatus:
        return cls(
            repo=state.repo,
            plugin=state.plugin,
            plugin_type=state.plugin_type,
            current_version=state.current_version,
            current_version_at=state.current_version_at,
            last_version=state.last_version,
            last_version_at=state.last_version_at,
            download_urls=state.download_urls,
            status=state.status,
            error=state.error,
            schedule=state.schedule,
            checked_at=state.checked_at,
            updated_at=state.updated_at,
        )


class CatalogItem(BaseModel):
    repo: str
    plugin: str
    plugin_type: str
    source_url: Optional[str] = None


class CatalogResponse(BaseModel):
    count: int
    sources: List[CatalogItem]


class SourcesResponse(BaseModel):
    count: int
    sources: List[SourceStatus]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    catalog_size: int
    admin_enabled: bool = Field(
        False, description="Whether admin operations are enabled (a token is configured)."
    )


class MessageResponse(BaseModel):
    message: str
    count: Optional[int] = None
