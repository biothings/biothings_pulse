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

        # 2. Expose a top-level ``config`` module for advanced plugins that do
        #    ``import config`` / ``from config import <X>``. It proxies our shim
        #    and, for any *unknown* repo-specific constant (e.g. MAX_REF_ALT_LEN,
        #    only used by upload/parse code), returns None so the dumper still
        #    loads. This is deliberately kept SEPARATE from the SDK's config
        #    module (hub_config) so the SDK's default_config fallback — which
        #    relies on AttributeError — is not disturbed.
        if "config" not in sys.modules:
            sys.modules["config"] = _make_plugin_config_module()

        # 3. Trigger SDK config initialisation (reads HUB_CONFIG).
        import biothings.hub  # noqa: F401  (side-effecting import)

        _ready = True


def _make_plugin_config_module():
    """Build the permissive top-level ``config`` module for plugin imports.

    Plugins expect ``config`` to behave like their hub's config, so we delegate
    to the SDK's initialised ``biothings.config`` (which carries default_config
    values like ``logger`` plus our shim settings). Repo-specific constants that
    aren't defined anywhere (e.g. ``TAXONOMY``, ``MAX_REF_ALT_LEN`` — used only
    by upload/parse code) resolve to ``None`` so the dumper can still load.
    """
    import types

    cfg = types.ModuleType("config")

    def _cfg_getattr(name: str):
        import biothings

        try:
            return getattr(biothings.config, name)
        except Exception:  # noqa: BLE001  (AttributeError / ConfigurationError)
            if name[:1].isupper():
                return None
            raise AttributeError(f"module 'config' has no attribute {name!r}") from None

    cfg.__getattr__ = _cfg_getattr  # PEP 562 module-level __getattr__
    return cfg


def get_dumper_module():
    """Return ``biothings.hub.dataload.dumper`` with the SDK initialised."""
    ensure_biothings_ready()
    import biothings.hub.dataload.dumper as dumper_module

    return dumper_module
