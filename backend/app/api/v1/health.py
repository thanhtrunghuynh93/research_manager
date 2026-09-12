"""Liveness, readiness, and Prometheus metrics (architecture §3, §12)."""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app.core import db
from app.core.config import Settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckState = Literal["ok", "fail", "skipped"]


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, CheckState]


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_database() -> CheckState:
    try:
        return "ok" if await db.ping() else "fail"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        log.warning("database readiness check failed: %s", exc)
        return "fail"


async def _check_object_storage(settings: Settings) -> CheckState:
    url = settings.s3_endpoint.rstrip("/") + "/minio/health/live"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(url)
        return "ok" if response.status_code == 200 else "fail"
    except httpx.HTTPError as exc:
        log.warning("object storage readiness check failed: %s", exc)
        return "fail"


@router.get("/readyz", summary="Readiness", response_model=Readiness)
async def readyz(request: Request, response: Response) -> Readiness:
    settings: Settings = request.app.state.settings
    checks: dict[str, CheckState] = {
        "database": await _check_database(),
        "object_storage": await _check_object_storage(settings),
    }
    ready = all(state == "ok" for state in checks.values())
    response.status_code = 200 if ready else 503
    return Readiness(status="ready" if ready else "degraded", checks=checks)


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(fresh: bool = False) -> Response:
    """Architecture §12: queue depth, sync staleness, model errors, citation and access failures.

    The gauges are refreshed by the worker's `queue_health` task every five minutes, so a scrape
    is a read of memory and cannot become load on the database. `?fresh=1` reads them now, for the
    case where an operator is looking at a system whose worker is the thing that has stopped.
    """
    if fresh:
        from app import observability

        try:
            async with db.session_factory()() as session:
                await observability.refresh(session)
        except Exception:  # noqa: BLE001 - a scrape must never fail on the thing it is measuring
            log.warning("could not refresh metrics on demand", exc_info=True)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
