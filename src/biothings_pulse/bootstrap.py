"""Bootstrap the BioThings SDK for standalone (Hub-less) use.

Importing any ``biothings.hub`` module eagerly initialises the SDK config from a
module named by the ``HUB_CONFIG`` env var. This module wires that up to our
SQLite-backed :mod:`biothings_pulse.hub_config` **before** the first hub import,
and injects the same module as the top-level ``config`` so advanced plugins that
``import config`` resolve against it.

Call :func:`ensure_biothings_ready` once, early, before importing dumpers.
"""

from __future__ import annotations

import os
import sys
import threading

_HUB_CONFIG_MODULE = "biothings_pulse.hub_config"
_lock = threading.Lock()
_ready = False


def ensure_biothings_ready() -> None:
    """Idempotently initialise the SDK config. Safe to call many times."""
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return

        # 1. Point the SDK at our config module (used by _config_for_app()).
        os.environ.setdefault("HUB_CONFIG", _HUB_CONFIG_MODULE)
        # Keep the SDK quiet unless explicitly debugging.
        os.environ.setdefault("HUB_VERBOSE", "0")

        # 2. Import our config module and expose it as top-level ``config`` so
        #    advanced plugin code doing ``import config`` / ``from config import
        #    DATA_ARCHIVE_ROOT`` resolves against our shim rather than failing.
        from biothings_pulse import hub_config

        sys.modules.setdefault("config", hub_config)

        # 3. Trigger SDK config initialisation (reads HUB_CONFIG).
        import biothings.hub  # noqa: F401  (side-effecting import)

        _ready = True


def get_dumper_module():
    """Return ``biothings.hub.dataload.dumper`` with the SDK initialised."""
    ensure_biothings_ready()
    import biothings.hub.dataload.dumper as dumper_module

    return dumper_module
