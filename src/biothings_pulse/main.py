"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import __version__
from .api.routes import router
from .bootstrap import ensure_biothings_ready
from .config import DEFAULT_ADMIN_TOKEN, Settings, get_settings
from .scheduler import RefreshScheduler
from .service import PulseService

logger = logging.getLogger(__name__)

_DASHBOARD_FILE = Path(__file__).resolve().parent / "static" / "dashboard.html"


def _initial_sync(service: PulseService) -> None:
    try:
        service.sync_and_discover()
        # Populate/refresh due sources once at startup (never-checked -> due, so a
        # fresh deployment fills in; a warm store only re-checks what's actually due).
        service.run_due_checks()
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
    if settings.admin_token == DEFAULT_ADMIN_TOKEN:
        logger.warning(
            "PULSE_ADMIN_TOKEN is the default %r — fine for dev, but set a real "
            "secret in production.",
            DEFAULT_ADMIN_TOKEN,
        )
    app = FastAPI(
        title="BioThings Pulse",
        version=__version__,
        description=(
            "Runs only the data-source-check step of BioThings data plugins and "
            "reports whether a new data release is available."
        ),
        lifespan=lifespan,
        # API + its docs live under /api; "/" serves the dashboard.
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.include_router(router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(_DASHBOARD_FILE, media_type="text/html")

    return app


# Module-level ASGI app for `uvicorn biothings_pulse.main:app`.
app = create_app()
