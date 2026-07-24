"""Background scheduler that checks due sources on a fixed tick.

Each tick, sources whose schedule is due are checked: a source follows its own
declared cron schedule when it has one, otherwise the Pulse default interval
(``scheduler_interval``). The tick (``scheduler_tick``) just sets the resolution
at which due-ness is evaluated.

Enabled by default for single-instance deployments. On multi-instance AWS,
disable it (``PULSE_SCHEDULER_ENABLED=false``) and drive checks externally via
EventBridge Scheduler -> ``POST /admin/refresh``.
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
        tick = self._settings.scheduler_tick
        self._scheduler.add_job(
            self._run,
            trigger="interval",
            seconds=tick,
            id="due_checks",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started (tick %ss, default cadence %ss)",
            tick,
            self._settings.scheduler_interval,
        )

    def _run(self) -> None:
        try:
            self._service.run_due_checks()
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled due-check failed")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
