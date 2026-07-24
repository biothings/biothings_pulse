"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .api.routes import router
from .bootstrap import ensure_biothings_ready
from .config import Settings, get_settings
from .scheduler import RefreshScheduler
from .service import PulseService

logger = logging.getLogger(__name__)


def _initial_sync(service: PulseService) -> None:
    try:
        service.sync_and_discover()
    except Exception:  # noqa: BLE001
        logger.exception("Initial sync/discovery failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    ensure_biothings_ready()

    service = PulseService(settings)
    app.state.service = service
    app.state.scheduler = None

    # Sync repos + discover in the background so startup stays fast; endpoints
    # return 404 for a source until discovery completes.
    if settings.sync_on_startup:
        threading.Thread(
            target=_initial_sync, args=(service,), name="pulse-initial-sync", daemon=True
        ).start()

    if settings.scheduler_enabled:
        scheduler = RefreshScheduler(service, settings)
        scheduler.start()
        app.state.scheduler = scheduler

    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown()
        service.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = FastAPI(
        title="BioThings Pulse",
        version=__version__,
        description=(
            "Runs only the data-source-check step of BioThings data plugins and "
            "reports whether a new data release is available."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(router)  # serves the dashboard at "/"
    return app


# Module-level ASGI app for `uvicorn biothings_pulse.main:app`.
app = create_app()
