"""Plugin sourcing: repo git-sync + plugin discovery."""

from .discovery import discover_plugins
from .models import PluginRef
from .sync import sync_registry, sync_repo

__all__ = ["PluginRef", "discover_plugins", "sync_repo", "sync_registry"]
