"""API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .. import __version__
from ..scheduling import next_check_at
from ..service import PulseService
from ..store.base import SourceState
from .models import (
    CatalogItem,
    CatalogResponse,
    HealthResponse,
    MessageResponse,
    SourcesResponse,
    SourceStatus,
)

router = APIRouter()

_DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


def get_service(request: Request) -> PulseService:
    return request.app.state.service


def _status(svc: PulseService, state: SourceState) -> SourceStatus:
    """Build the response, filling next_check_at from the schedule."""
    st = SourceStatus.from_state(state)
    if state.checked_at is not None:
        st.next_check_at = next_check_at(
            state.schedule, state.checked_at, svc.settings.scheduler_interval
        )
    return st


@router.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the Pulse dashboard landing page (reads /sources via JS)."""
    return FileResponse(_DASHBOARD_FILE, media_type="text/html")


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health(svc: PulseService = Depends(get_service)) -> HealthResponse:
    return HealthResponse(
        version=__version__, catalog_size=len(svc.list_catalog())
    )


@router.get("/sources", response_model=SourcesResponse, tags=["sources"])
def list_sources(svc: PulseService = Depends(get_service)) -> SourcesResponse:
    """List every discovered source with its last-known (cached) status."""
    statuses = []
    for ref in svc.list_catalog():
        state = svc.store.get(ref.repo, ref.name) or SourceState(
            repo=ref.repo, plugin=ref.name, plugin_type=ref.plugin_type
        )
        statuses.append(_status(svc, state))
    return SourcesResponse(count=len(statuses), sources=statuses)


@router.get("/catalog", response_model=CatalogResponse, tags=["sources"])
def catalog(svc: PulseService = Depends(get_service)) -> CatalogResponse:
    """List discovered sources without touching the state store."""
    items = [
        CatalogItem(repo=r.repo, plugin=r.name, plugin_type=r.plugin_type)
        for r in svc.list_catalog()
    ]
    return CatalogResponse(count=len(items), sources=items)


@router.get(
    "/sources/{repo}/{plugin}", response_model=SourceStatus, tags=["sources"]
)
def get_source(
    repo: str,
    plugin: str,
    refresh: bool = Query(
        False, description="Force a fresh live check instead of returning cached state."
    ),
    svc: PulseService = Depends(get_service),
) -> SourceStatus:
    # Reads are cheap (cached); only ?refresh=true triggers a live check.
    state = svc.check_source(repo, plugin) if refresh else svc.get_status(repo, plugin)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {repo}/{plugin}")
    return _status(svc, state)


@router.post(
    "/sources/{repo}/{plugin}/check", response_model=SourceStatus, tags=["sources"]
)
def check_source(
    repo: str, plugin: str, svc: PulseService = Depends(get_service)
) -> SourceStatus:
    state = svc.check_source(repo, plugin)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {repo}/{plugin}")
    return _status(svc, state)


@router.post("/admin/sync", response_model=MessageResponse, tags=["admin"])
def admin_sync(svc: PulseService = Depends(get_service)) -> MessageResponse:
    count = svc.sync_and_discover()
    return MessageResponse(message="synced and rediscovered", count=count)


@router.post("/admin/refresh", response_model=MessageResponse, tags=["admin"])
def admin_refresh(svc: PulseService = Depends(get_service)) -> MessageResponse:
    count = svc.refresh_all()
    return MessageResponse(message="refreshed all sources", count=count)
