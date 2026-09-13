"""Liveness, readiness, and Prometheus metrics (architecture §3, §12)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app.core import db
from app.core.clock import now
from app.core.config import Settings
from app.core.errors import UnauthenticatedError
from app.core.storage import current_store

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckState = Literal["ok", "fail", "skipped"]

# `?fresh=1` runs the full observability query set. One operator watching a stalled worker is the
# use; a scrape loop against it is not, so it is rate-limited rather than left to the caller.
FRESH_MIN_INTERVAL = timedelta(seconds=30)
_last_fresh: datetime | None = None


def _refresh_allowed() -> bool:
    global _last_fresh
    at = now()
    if _last_fresh is not None and at - _last_fresh < FRESH_MIN_INTERVAL:
        return False
    _last_fresh = at
    return True


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
    """Reachable *and* holding the bucket.

    A liveness ping alone answered "ok" for a store with no bucket in it, which is the one failure
    that stops every upload (REP-04).
    """
    try:
        return "ok" if await current_store().bucket_ready() else "fail"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
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


def _may_scrape(request: Request, settings: Settings) -> bool:
    """Whether this caller may read the gauges.

    `/metrics` sits under `/api`, which the reverse proxy publishes wholesale, so "only Prometheus
    can reach it" was never true. The gauges describe every workspace's queue and sync health, and
    `?fresh=1` lets an anonymous caller turn each request into the full query set.

    A deployment without a token configured is a development or pilot one, and is left open so
    nobody has to invent a secret to run the stack locally — except in prod, where a missing token
    is a misconfiguration and the safe reading of it is "nobody".
    """
    configured = settings.metrics_token.get_secret_value()
    if not configured:
        if settings.env == "prod":
            log.error("RM_METRICS_TOKEN is not set; refusing to serve /metrics")
            return False
        return True

    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return secrets.compare_digest(presented.strip(), configured)


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(request: Request, fresh: bool = False) -> Response:
    """Architecture §12: queue depth, sync staleness, model errors, citation and access failures.

    The gauges are refreshed by the worker's `queue_health` task every five minutes, so a scrape
    is a read of memory and cannot become load on the database. `?fresh=1` reads them now, for the
    case where an operator is looking at a system whose worker is the thing that has stopped.
    """
    settings: Settings = request.app.state.settings
    if not _may_scrape(request, settings):
        raise UnauthenticatedError("this endpoint requires a metrics token")

    if fresh and _refresh_allowed():
        from app import observability

        try:
            async with db.session_factory()() as session:
                await observability.refresh(session)
        except Exception:  # noqa: BLE001 - a scrape must never fail on the thing it is measuring
            log.warning("could not refresh metrics on demand", exc_info=True)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
