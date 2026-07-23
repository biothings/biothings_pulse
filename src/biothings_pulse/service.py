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

    def _run_check(self, ref: PluginRef) -> CheckResult:
        """Run one check in the threadpool, bounded by the configured timeout."""
        future = self._executor.submit(check_plugin, ref, self.settings)
        try:
            return future.result(timeout=self.settings.check_timeout)
        except FutureTimeout:
            # NOTE: the worker thread may still be running; it is bounded by the
            # pool size. A future improvement is subprocess isolation with hard
            # cancellation.
            return CheckResult(
                status="error",
                error=f"check timed out after {self.settings.check_timeout}s",
            )

    def check_source(self, repo: str, plugin: str) -> Optional[SourceState]:
        """Force a fresh check and persist the outcome. None if unknown source."""
        ref = self.get_ref(repo, plugin)
        if ref is None:
            return None
        result = self._run_check(ref)
        return self.store.record_check(
            repo,
            plugin,
            ref.plugin_type,
            latest_version=result.latest_version,
            download_urls=result.download_urls,
            status=result.status,
            error=result.error,
        )

    def get_status(
        self, repo: str, plugin: str, allow_stale: bool = True
    ) -> Optional[SourceState]:
        """Return stored status, refreshing when missing or (optionally) stale."""
        if self.get_ref(repo, plugin) is None:
            return None
        state = self.store.get(repo, plugin)
        if state is None or (
            not allow_stale and state.is_stale(self.settings.check_ttl)
        ):
            return self.check_source(repo, plugin)
        return state

    def refresh_all(self) -> int:
        """Check every catalogued source; persist results. Returns #checked."""
        refs = self.list_catalog()
        futures = {
            r.key: self._executor.submit(check_plugin, r, self.settings) for r in refs
        }
        checked = 0
        for ref in refs:
            try:
                result = futures[ref.key].result(timeout=self.settings.check_timeout)
            except FutureTimeout:
                result = CheckResult(status="error", error="check timed out")
            self.store.record_check(
                ref.repo,
                ref.name,
                ref.plugin_type,
                latest_version=result.latest_version,
                download_urls=result.download_urls,
                status=result.status,
                error=result.error,
            )
            checked += 1
        logger.info("Refreshed %d sources", checked)
        return checked

    def acknowledge(self, repo: str, plugin: str) -> Optional[SourceState]:
        return self.store.acknowledge(repo, plugin)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
