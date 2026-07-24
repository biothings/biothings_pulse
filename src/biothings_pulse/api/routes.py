"""API endpoints (mounted under the /api prefix by the app)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request

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


def get_service(request: Request) -> PulseService:
    return request.app.state.service


def _presented_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Admin-Token")


def _verify_admin(request: Request, svc: PulseService) -> None:
    """Authorize a mutating/admin operation. Read-only by default."""
    token = svc.settings.admin_token
    if not token:
        raise HTTPException(
            status_code=403,
            detail="Admin operations are disabled. Set PULSE_ADMIN_TOKEN to enable them.",
        )
    presented = _presented_token(request)
    if not presented or not secrets.compare_digest(presented, token):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin(
    request: Request, svc: PulseService = Depends(get_service)
) -> None:
    """FastAPI dependency guarding admin endpoints."""
    _verify_admin(request, svc)


def _status(svc: PulseService, state: SourceState) -> SourceStatus:
    """Build the response, filling next_check_at and source_url."""
    st = SourceStatus.from_state(state)
    if state.checked_at is not None:
        st.next_check_at = next_check_at(
            state.schedule, state.checked_at, svc.settings.scheduler_interval
        )
    ref = svc.get_ref(state.repo, state.plugin)
    if ref is not None:
        st.source_url = ref.source_url
    return st


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health(svc: PulseService = Depends(get_service)) -> HealthResponse:
    return HealthResponse(
        version=__version__,
        catalog_size=len(svc.list_catalog()),
        admin_enabled=bool(svc.settings.admin_token),
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
        CatalogItem(
            repo=r.repo,
            plugin=r.name,
            plugin_type=r.plugin_type,
            source_url=r.source_url,
        )
        for r in svc.list_catalog()
    ]
    return CatalogResponse(count=len(items), sources=items)


@router.get(
    "/sources/{repo}/{plugin}", response_model=SourceStatus, tags=["sources"]
)
def get_source(
    repo: str,
    plugin: str,
    request: Request,
    refresh: bool = Query(
        False,
        description="Force a fresh live check (admin-only) instead of cached state.",
    ),
    svc: PulseService = Depends(get_service),
) -> SourceStatus:
    # Reads are cheap (cached); ?refresh=true forces a live check and is admin-only.
    if refresh:
        _verify_admin(request, svc)
        state = svc.check_source(repo, plugin)
    else:
        state = svc.get_status(repo, plugin)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {repo}/{plugin}")
    return _status(svc, state)


@router.post(
    "/sources/{repo}/{plugin}/check",
    response_model=SourceStatus,
    tags=["sources"],
    dependencies=[Depends(require_admin)],
)
def check_source(
    repo: str, plugin: str, svc: PulseService = Depends(get_service)
) -> SourceStatus:
    state = svc.check_source(repo, plugin)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {repo}/{plugin}")
    return _status(svc, state)


@router.post(
    "/admin/sync",
    response_model=MessageResponse,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
def admin_sync(svc: PulseService = Depends(get_service)) -> MessageResponse:
    count = svc.sync_and_discover()
    return MessageResponse(message="synced and rediscovered", count=count)


@router.post(
    "/admin/refresh",
    response_model=MessageResponse,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)
def admin_refresh(svc: PulseService = Depends(get_service)) -> MessageResponse:
    count = svc.refresh_all()
    return MessageResponse(message="refreshed all sources", count=count)
