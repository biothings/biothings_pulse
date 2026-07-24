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
        # Honor a manifest-declared check schedule (cron); None -> Pulse default.
        "SCHEDULE": section.get("schedule"),
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


def _dumper_classes_in(module, defined_in) -> list:
    """Concrete BaseDumper subclasses *defined in* ``module`` (per ``defined_in``).

    ``defined_in(cls.__module__) -> bool`` filters out imported base classes
    (e.g. HTTPDumper) so we only pick up the plugin's own dumper.
    """
    import inspect

    base = get_dumper_module().BaseDumper
    out = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, base)
            and obj is not base
            and defined_in(getattr(obj, "__module__", ""))
            and getattr(obj, "SRC_NAME", None)
        ):
            out.append(obj)
    return out


def _best(classes: list):
    # Prefer the most-derived class (in case of a small hierarchy).
    return sorted(classes, key=lambda c: len(c.__mro__))[-1] if classes else None


def _instantiate(klass):
    try:
        return klass()
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"instantiating {klass.__name__} failed: {exc}") from exc


def _load_dumper_by_file(source_dir: Path):
    """Load the dumper module by file path, bypassing the package ``__init__``.

    Advanced plugins' ``__init__.py`` typically imports the uploader/parser too,
    which pull in Hub-only or heavy dependencies that fail outside a running Hub
    (e.g. mychem.info/chembl's key-lookup). The dumper module itself is usually
    self-contained, so load it directly. Returns an instantiated dumper, or
    ``None`` if no dumper file/class was found (caller then tries the package).
    """
    _, dotted = _package_root_and_module(source_dir)
    prefix = "pulseadv_" + dotted.replace(".", "_")
    # Prefer files that look like a dumper module (``dumper.py``/``*_dump.py``).
    candidates = sorted(
        (p for p in source_dir.glob("*.py") if "dump" in p.stem.lower()),
        key=lambda p: (p.stem.lower() not in ("dumper", "dump"), p.name),
    )
    for pyfile in candidates:
        unique = f"{prefix}_{pyfile.stem}"
        spec = importlib.util.spec_from_file_location(unique, pyfile)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[unique] = mod  # reuse the stable name on re-checks
        try:
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001
            # e.g. relative imports needing package context; fall back to package.
            sys.modules.pop(unique, None)
            continue
        klass = _best(_dumper_classes_in(mod, lambda m, u=unique: m == u))
        if klass is not None:
            return _instantiate(klass)
    return None


def _find_dumper_class(module, dotted_prefix: str):
    """Locate a concrete BaseDumper subclass defined within the package."""
    classes = _dumper_classes_in(module, lambda m: m.startswith(dotted_prefix))
    # Also scan a `dumper`/`dump` submodule if __init__ doesn't expose one.
    for subname in ("dumper", "dump"):
        try:
            sub = importlib.import_module(f"{dotted_prefix}.{subname}")
        except Exception:  # noqa: BLE001
            continue
        classes += _dumper_classes_in(sub, lambda m: m.startswith(dotted_prefix))
    return _best(classes)


def _hub_src_root(source_dir: Path):
    """For a ``.../hub/dataload/sources/<name>`` source, return the dir that
    contains ``hub/`` (the '[src]' dir).

    Advanced dumpers commonly use absolute imports like
    ``from hub.dataload.sources.<other> import ...``. That only resolves if the
    dir containing ``hub/`` is on ``sys.path`` — which isn't the case when an
    intermediate dir (e.g. ``src/``) is itself a package (then the package root
    walks up past it). Adding this dir makes ``import hub.*`` work.
    """
    p = source_dir.resolve()
    parents = p.parents
    if (
        len(parents) >= 4
        and p.parent.name == "sources"
        and parents[1].name == "dataload"
        and parents[2].name == "hub"
    ):
        return parents[3]
    return None


def load_advanced_dumper(ref: PluginRef, work_dir: Path):
    """Import an advanced plugin's dumper class and instantiate it."""
    ensure_biothings_ready()  # also injects the `config` shim for `import config`
    # Import the dumper module so the ``biothings.hub.dataload.dumper`` attribute
    # chain exists — some plugins do ``import biothings`` then reference
    # ``biothings.hub.dataload.dumper.<Class>`` at class-definition time.
    get_dumper_module()

    source_dir = Path(ref.path)
    sys_path_entry, dotted = _package_root_and_module(source_dir)

    # Path entries needed for the plugin's imports to resolve.
    entries = [sys_path_entry]
    hub_root = _hub_src_root(source_dir)
    if hub_root is not None and hub_root not in entries:
        entries.append(hub_root)

    added = []
    try:
        for entry in entries:
            if str(entry) not in sys.path:
                sys.path.insert(0, str(entry))
                added.append(str(entry))

        # Preferred: load the dumper module directly, bypassing the package
        # __init__ (which may import uploader/parser code needing a full Hub).
        dumper = _load_dumper_by_file(source_dir)
        if dumper is not None:
            return dumper

        # Fallback: import the whole package (handles dumpers that rely on
        # relative imports or are only exposed via __init__).
        try:
            module = importlib.import_module(dotted)
        except Exception as exc:  # noqa: BLE001
            raise LoaderError(f"import of {dotted} failed: {exc}") from exc

        klass = _find_dumper_class(module, dotted)
        if klass is None:
            raise UnsupportedPlugin("no BaseDumper subclass found in package")
        return _instantiate(klass)
    finally:
        for entry in added:
            try:
                sys.path.remove(entry)
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
