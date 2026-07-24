"""Application service: catalog + check orchestration + state persistence.

This is the seam the API routes and the scheduler both call. It owns the plugin
catalog (discovered ``PluginRef`` objects), a threadpool that runs blocking
checks with a timeout, and the state store.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Dict, List, Optional

from .checker.models import CheckResult
from .checker.runner import check_plugin
from .config import Settings
from .plugins.discovery import discover_plugins
from .plugins.models import PluginRef
from .plugins.sync import sync_registry
from .scheduling import is_due
from .store import StateStore, make_store
from .store.base import SourceState

logger = logging.getLogger(__name__)


class PulseService:
    def __init__(self, settings: Settings, store: Optional[StateStore] = None):
        self.settings = settings
        self.store = store or make_store(settings)
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_check_workers,
            thread_name_prefix="pulse-check",
        )
        self._catalog: Dict[str, PluginRef] = {}

    # -- catalog ----------------------------------------------------------

    def sync_and_discover(self) -> int:
        """Git-sync all repos and (re)build the plugin catalog. Returns count."""
        registry = self.settings.load_registry()
        repos = registry.resolved_repos()
        local_paths = sync_registry(repos, self.settings)

        catalog: Dict[str, PluginRef] = {}
        for spec in repos:
            path = local_paths.get(spec.name)
            if path is None:
                continue
            for ref in discover_plugins(spec.name, path, spec):
                catalog[ref.key] = ref
        self._catalog = catalog
        logger.info("Catalog rebuilt: %d plugins", len(catalog))
        return len(catalog)

    def list_catalog(self) -> List[PluginRef]:
        return sorted(self._catalog.values(), key=lambda r: r.key)

    def get_ref(self, repo: str, plugin: str) -> Optional[PluginRef]:
        return self._catalog.get(f"{repo}/{plugin}")

    # -- checking ---------------------------------------------------------

    def _record(self, ref: PluginRef, result: CheckResult) -> SourceState:
        return self.store.record_check(
            ref.repo,
            ref.name,
            ref.plugin_type,
            detected_version=result.latest_version,
            download_urls=result.download_urls,
            status=result.status,
            error=result.error,
            schedule=result.schedule,
        )

    def _check_refs(self, refs: List[PluginRef]) -> int:
        """Check the given refs concurrently and persist each result."""
        futures = {
            r.key: self._executor.submit(check_plugin, r, self.settings) for r in refs
        }
        for ref in refs:
            try:
                result = futures[ref.key].result(timeout=self.settings.check_timeout)
            except FutureTimeout:
                result = CheckResult(status="error", error="check timed out")
            self._record(ref, result)
        return len(refs)

    def check_source(self, repo: str, plugin: str) -> Optional[SourceState]:
        """Force a fresh check and persist the outcome. None if unknown source."""
        ref = self.get_ref(repo, plugin)
        if ref is None:
            return None
        future = self._executor.submit(check_plugin, ref, self.settings)
        try:
            result = future.result(timeout=self.settings.check_timeout)
        except FutureTimeout:
            result = CheckResult(
                status="error",
                error=f"check timed out after {self.settings.check_timeout}s",
            )
        return self._record(ref, result)

    def get_status(self, repo: str, plugin: str) -> Optional[SourceState]:
        """Return the cached status (or a 'pending' placeholder) without checking.

        Reads are cheap so downstream consumers can poll freely; live checks only
        happen via the background scheduler or an explicit check (POST /check or
        ``?refresh=true``). Returns None only when the source isn't in the catalog.
        """
        ref = self.get_ref(repo, plugin)
        if ref is None:
            return None
        return self.store.get(repo, plugin) or SourceState(
            repo=repo, plugin=plugin, plugin_type=ref.plugin_type
        )

    def refresh_all(self) -> int:
        """Force-check every catalogued source. Returns #checked."""
        n = self._check_refs(self.list_catalog())
        logger.info("Refreshed all %d sources", n)
        return n

    def run_due_checks(self) -> int:
        """Check only sources whose schedule is due, then persist. Returns #checked.

        A source uses its own declared cron schedule when it has one, otherwise
        the Pulse default interval. Never-checked sources are always due (this is
        what populates a fresh deployment).
        """
        due = [ref for ref in self.list_catalog() if self._is_due(ref)]
        if due:
            self._check_refs(due)
        logger.info("Due-check: %d of %d sources due", len(due), len(self._catalog))
        return len(due)

    def _is_due(self, ref: PluginRef) -> bool:
        state = self.store.get(ref.repo, ref.name)
        last = state.checked_at if state else None
        schedule = state.schedule if state else None
        return is_due(schedule, last, self.settings.scheduler_interval)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
