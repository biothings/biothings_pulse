"""Run the check step for a plugin and produce a :class:`CheckResult`.

The check calls ``create_todump_list(force=True)`` — which triggers
``set_release()`` and per-URL freshness comparison — but never downloads
anything. ``latest_version`` comes from ``dumper.release`` and the download URLs
from ``dumper.to_dump``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import tempfile
from pathlib import Path

from ..config import Settings
from ..plugins.models import PluginRef
from .loader import LoaderError, UnsupportedPlugin, load_dumper
from .models import CheckResult

logger = logging.getLogger(__name__)


def _run_create_todump(dumper) -> None:
    fn = dumper.create_todump_list
    if inspect.iscoroutinefunction(fn):
        asyncio.run(fn(force=True))
    else:
        fn(force=True)


def _ensure_release(dumper) -> None:
    """Some custom dumpers set release outside create_todump_list."""
    if getattr(dumper, "release", None) is not None:
        return
    set_release = getattr(dumper, "set_release", None)
    if not callable(set_release):
        return
    try:
        returned = set_release()
        if getattr(dumper, "release", None) is None and returned:
            dumper.release = returned
    except NotImplementedError:
        pass
    except Exception:  # noqa: BLE001
        logger.debug("set_release fallback failed", exc_info=True)


def run_dumper_check(dumper) -> CheckResult:
    """Drive an already-instantiated dumper through release detection."""
    schedule = getattr(type(dumper), "SCHEDULE", None) or None
    try:
        _run_create_todump(dumper)
        _ensure_release(dumper)
        latest = getattr(dumper, "release", None)
        urls = [str(d["remote"]) for d in getattr(dumper, "to_dump", []) if "remote" in d]
        if latest is None and not urls:
            # No remote version to detect — typically a manual/derived source.
            return CheckResult(
                status="unsupported",
                error="no remote version detected (manual/derived source?)",
                schedule=schedule,
            )
        return CheckResult(
            status="ok",
            latest_version=str(latest) if latest is not None else None,
            download_urls=urls,
            schedule=schedule,
        )
    except NotImplementedError:
        # The dumper doesn't implement release detection (e.g. ManualDumper).
        return CheckResult(
            status="unsupported",
            error="dumper does not implement release detection (manual/derived source)",
            schedule=schedule,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("check failed for %s: %s", getattr(dumper, "src_name", "?"), exc)
        return CheckResult(
            status="error", error=f"{type(exc).__name__}: {exc}", schedule=schedule
        )
    finally:
        _release_client(dumper)


def _release_client(dumper) -> None:
    try:
        release = getattr(dumper, "release_client", None)
        if callable(release) and dumper._state.get("client"):
            release()
    except Exception:  # noqa: BLE001
        pass


def check_plugin(ref: PluginRef, settings: Settings) -> CheckResult:
    """Load and check a plugin in an isolated scratch dir. Never raises."""
    archive_root = settings.data_archive_root
    base_dir = None
    if archive_root is not None:
        Path(archive_root).mkdir(parents=True, exist_ok=True)
        base_dir = str(archive_root)

    with tempfile.TemporaryDirectory(prefix="pulse_", dir=base_dir) as work:
        try:
            dumper = load_dumper(ref, Path(work))
        except UnsupportedPlugin as exc:
            return CheckResult(status="unsupported", error=str(exc))
        except LoaderError as exc:
            return CheckResult(status="error", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                status="error", error=f"loader crashed: {type(exc).__name__}: {exc}"
            )
        return run_dumper_check(dumper)
