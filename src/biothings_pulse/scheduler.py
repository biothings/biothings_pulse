"""Background scheduler that periodically refreshes all sources.

Enabled by default for single-instance deployments. On multi-instance AWS,
disable it (``PULSE_SCHEDULER_ENABLED=false``) and drive refreshes externally
via EventBridge Scheduler -> ``POST /admin/refresh``.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import Settings
from .service import PulseService

logger = logging.getLogger(__name__)


class RefreshScheduler:
    def __init__(self, service: PulseService, settings: Settings):
        self._service = service
        self._settings = settings
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        interval = self._settings.scheduler_interval
        self._scheduler.add_job(
            self._run,
            trigger="interval",
            seconds=interval,
            id="refresh_all",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("Refresh scheduler started (every %ss)", interval)

    def _run(self) -> None:
        try:
            self._service.refresh_all()
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled refresh failed")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
