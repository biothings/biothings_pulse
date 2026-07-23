"""Lightweight descriptors for a discovered plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class PluginRef(BaseModel):
    """A discovered data plugin, before any code is loaded.

    ``path`` is the plugin directory. For manifest plugins ``manifest_path``
    points at the ``manifest.json``. For advanced plugins ``path`` is the source
    package directory under ``hub/dataload/sources/``.
    """

    model_config = {"arbitrary_types_allowed": True}

    repo: str
    name: str
    plugin_type: str  # "manifest" | "advanced"
    path: Path
    manifest_path: Optional[Path] = None

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.name}"
