"""Turn a :class:`PluginRef` into an instantiated BioThings dumper.

Manifest plugins are reconstructed the way the SDK's ``ManifestBasedPluginLoader``
does (URL scheme -> ``LastModifiedHTTPDumper``/``LastModifiedFTPDumper``, plus an
optional ``release`` function), but without the Hub DB / manager coupling.
Advanced plugins are imported from their source package and the ``BaseDumper``
subclass is located and instantiated.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Callable, List

from ..bootstrap import ensure_biothings_ready, get_dumper_module
from ..plugins.models import PluginRef

logger = logging.getLogger(__name__)

# Loading a plugin mutates process-global state (sys.path, sys.modules, dynamic
# imports). Checks run concurrently in a threadpool, so serialise the *loading*
# phase. The subsequent network check runs unlocked.
_load_lock = threading.RLock()


class UnsupportedPlugin(Exception):
    """The plugin cannot be checked (e.g. no dumper, docker-only)."""


class LoaderError(Exception):
    """The plugin should be checkable but loading its dumper failed."""


# ---------------------------------------------------------------------------
# Manifest-based plugins
# ---------------------------------------------------------------------------

def _load_manifest(ref: PluginRef) -> dict:
    assert ref.manifest_path is not None
    try:
        return json.loads(Path(ref.manifest_path).read_text())
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Cannot parse manifest.json: {exc}") from exc


def _import_release_func(plugin_dir: Path, mod_spec: str) -> Callable:
    """Import ``module:func`` from the plugin directory (mirrors the SDK)."""
    try:
        module, funcname = (s.strip() for s in mod_spec.split(":"))
    except ValueError as exc:
        raise LoaderError(
            f"Invalid release spec {mod_spec!r}, expected 'module:func'"
        ) from exc

    module_file = plugin_dir / f"{module}.py"
    added_path = False
    try:
        if module_file.exists():
            if str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))
                added_path = True
            unique = f"pulse_plugin_{plugin_dir.name}_{module}"
            spec = importlib.util.spec_from_file_location(unique, module_file)
            if spec is None or spec.loader is None:
                raise LoaderError(f"cannot load module {module!r}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        else:
            mod = importlib.import_module(module)
        func = getattr(mod, funcname, None)
        if func is None:
            raise LoaderError(f"Function {funcname!r} not found in {module!r}")
        return func
    finally:
        if added_path:
            sys.path.remove(str(plugin_dir))


_SCHEME_BASES = {"http": "http", "https": "http", "ftp": "ftp"}


def build_manifest_dumper(ref: PluginRef, work_dir: Path):
    """Construct (do not run) a dumper instance for a manifest plugin."""
    ensure_biothings_ready()
    dumper_mod = get_dumper_module()
    from biothings.utils.common import get_class_from_classpath

    manifest = _load_manifest(ref)
    section = manifest.get("dumper") or {}
    data_url = section.get("data_url")
    if not data_url:
        raise UnsupportedPlugin("manifest has no dumper.data_url (upload-only)")

    urls: List[str] = [data_url] if isinstance(data_url, str) else list(data_url)
    schemes = {urllib.parse.urlsplit(u).scheme for u in urls}
    normalized = {s.replace("https", "http") for s in schemes}
    if len(normalized) != 1:
        raise UnsupportedPlugin(f"mixed URL schemes: {schemes}")
    scheme = schemes.pop()
    if "docker" in scheme:
        raise UnsupportedPlugin("docker-based dumper is not supported")

    # Base class: explicit manifest 'class', else scheme default.
    custom_class = section.get("class")
    if custom_class:
        base = get_class_from_classpath(custom_class)
    else:
        base_kind = _SCHEME_BASES.get(scheme)
        if base_kind == "http":
            base = dumper_mod.LastModifiedHTTPDumper
        elif base_kind == "ftp":
            base = dumper_mod.LastModifiedFTPDumper
        else:
            raise UnsupportedPlugin(f"unsupported URL scheme {scheme!r}")

    attrs = {
        "SRC_NAME": ref.name,
        "SRC_ROOT_FOLDER": str(Path(work_dir) / ref.name),
        "SRC_URLS": urls,
        "SCHEDULE": None,
        "UNCOMPRESS": section.get("uncompress", False),
    }

    # Optional custom release function -> set_release method.
    release_spec = section.get("release")
    if release_spec:
        release_func = _import_release_func(Path(ref.path), release_spec)

        def set_release(self, _func=release_func):
            self.release = _func(self)

        attrs["set_release"] = set_release

    klass = type(f"{ref.name.capitalize()}Dumper", (base,), attrs)
    return klass()


# ---------------------------------------------------------------------------
# Advanced plugins
# ---------------------------------------------------------------------------

def _package_root_and_module(source_dir: Path) -> tuple[Path, str]:
    """Find the sys.path entry and dotted module name for a source package.

    Walks up while parent dirs remain Python packages (contain __init__.py).
    """
    source_dir = source_dir.resolve()
    top = source_dir
    while (top.parent / "__init__.py").exists():
        top = top.parent
    sys_path_entry = top.parent
    rel = source_dir.relative_to(sys_path_entry)
    dotted = ".".join(rel.parts)
    return sys_path_entry, dotted


def _find_dumper_class(module, dotted_prefix: str):
    """Locate a concrete BaseDumper subclass defined within the package."""
    import inspect

    dumper_mod = get_dumper_module()
    base = dumper_mod.BaseDumper

    candidates = []
    modules_to_scan = [module]
    # Also scan a `dumper` submodule if the package __init__ doesn't expose one.
    for subname in ("dumper", "dump"):
        try:
            sub = importlib.import_module(f"{dotted_prefix}.{subname}")
            modules_to_scan.append(sub)
        except Exception:  # noqa: BLE001
            pass

    for mod in modules_to_scan:
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, base)
                and obj is not base
                and getattr(obj, "__module__", "").startswith(dotted_prefix)
                and getattr(obj, "SRC_NAME", None)
            ):
                candidates.append(obj)

    if not candidates:
        return None
    # Prefer the most-derived class (in case of a small hierarchy).
    return sorted(candidates, key=lambda c: len(c.__mro__))[-1]


def load_advanced_dumper(ref: PluginRef, work_dir: Path):
    """Import an advanced plugin's dumper class and instantiate it."""
    ensure_biothings_ready()  # also injects the `config` shim for `import config`
    # Import the dumper module so the ``biothings.hub.dataload.dumper`` attribute
    # chain exists — some plugins do ``import biothings`` then reference
    # ``biothings.hub.dataload.dumper.<Class>`` at class-definition time.
    get_dumper_module()

    source_dir = Path(ref.path)
    sys_path_entry, dotted = _package_root_and_module(source_dir)

    added = False
    try:
        if str(sys_path_entry) not in sys.path:
            sys.path.insert(0, str(sys_path_entry))
            added = True
        try:
            module = importlib.import_module(dotted)
        except Exception as exc:  # noqa: BLE001
            raise LoaderError(f"import of {dotted} failed: {exc}") from exc

        klass = _find_dumper_class(module, dotted)
        if klass is None:
            raise UnsupportedPlugin("no BaseDumper subclass found in package")
        try:
            return klass()
        except Exception as exc:  # noqa: BLE001
            raise LoaderError(f"instantiating {klass.__name__} failed: {exc}") from exc
    finally:
        if added:
            try:
                sys.path.remove(str(sys_path_entry))
            except ValueError:
                pass


# ---------------------------------------------------------------------------

def load_dumper(ref: PluginRef, work_dir: Path):
    """Dispatch by plugin type to build a dumper instance (not yet run)."""
    with _load_lock:
        if ref.plugin_type == "manifest":
            return build_manifest_dumper(ref, work_dir)
        if ref.plugin_type == "advanced":
            return load_advanced_dumper(ref, work_dir)
        raise UnsupportedPlugin(f"unknown plugin type {ref.plugin_type!r}")
