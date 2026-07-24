"""Lightweight descriptors for a discovered plugin."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class PluginRef(BaseModel):
    """A discovered data plugin, before any code is loaded.

    ``path`` is the plugin directory. For manifest plugins ``manifest_path``
    points at the ``manifest.json``. For advanced plugins ``path`` is the source
    package directory under ``hub/dataload/sources/``. ``repo_path`` is the repo
    checkout root (used to resolve shared modules a manifest ``release`` function
    may live in, e.g. ``hub.dataload.metadata_parser``).
    """

    model_config = {"arbitrary_types_allowed": True}

    repo: str
    name: str
    plugin_type: str  # "manifest" | "advanced"
    path: Path
    manifest_path: Optional[Path] = None
    repo_path: Optional[Path] = None
    source_url: Optional[str] = None  # web link to the plugin's source code
    extra_sys_path: List[Path] = Field(default_factory=list)  # repo-configured sys.path dirs

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.name}"
