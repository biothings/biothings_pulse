"""State store for BioThings Pulse.

The store is the *only* source of truth for a source's "current version".
``has_update`` is computed as: a check produced a ``latest_version`` that differs
from the stored ``current_version``.
"""

from .base import SourceState, StateStore
from .factory import make_store

__all__ = ["SourceState", "StateStore", "make_store"]
