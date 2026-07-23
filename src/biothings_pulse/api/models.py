"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ..store.base import SourceState


class SourceStatus(BaseModel):
    """The core per-source status payload."""

    repo: str
    plugin: str
    plugin_type: str
    has_update: bool = Field(
        description="True if a newer version was detected than the tracked current one."
    )
    current_version: Optional[str] = Field(
        None, description="Version currently tracked/acknowledged by Pulse."
    )
    latest_version: Optional[str] = Field(
        None, description="Latest version detected on the remote source."
    )
    download_urls: List[str] = Field(
        default_factory=list, description="URLs the plugin would download."
    )
    status: str = Field(description="ok | error | unsupported | pending")
    error: Optional[str] = None
    checked_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_state(cls, state: SourceState) -> SourceStatus:
        return cls(
            repo=state.repo,
            plugin=state.plugin,
            plugin_type=state.plugin_type,
            has_update=state.has_update,
            current_version=state.current_version,
            latest_version=state.latest_version,
            download_urls=state.download_urls,
            status=state.status,
            error=state.error,
            checked_at=state.checked_at,
            updated_at=state.updated_at,
        )


class CatalogItem(BaseModel):
    repo: str
    plugin: str
    plugin_type: str


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


class MessageResponse(BaseModel):
    message: str
    count: Optional[int] = None
