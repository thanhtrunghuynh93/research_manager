"""Liveness, readiness, and Prometheus metrics (architecture §3, §12)."""

from __future__ import annotations

import asyncio
import logging
import secrets
import smtplib
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text

from app.core import db
from app.core.clock import now
from app.core.config import Settings
from app.core.errors import UnauthenticatedError
from app.core.storage import current_store

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckState = Literal["ok", "fail", "skipped"]

# A worker running the periodic tasks completes `queue_health` every five minutes, so silence for
# three cycles means nothing is consuming. The same window decides when a `todo` job is old enough
# to be evidence rather than ordinary latency.
WORKER_SILENT_AFTER = timedelta(minutes=15)

# An SMTP relay is a third party with its own opinion about how often it may be connected to, and
# readiness is polled. The result is reused for this long rather than reconnecting per request.
# Ten minutes rather than one: a full login against Gmail every minute is enough traffic for the
# relay to start closing connections, which made readiness flap between ok and fail on a healthy
# deployment — the check was reporting on how often it ran, not on whether mail works.
SMTP_CHECK_TTL = timedelta(minutes=10)

# Long enough for a STARTTLS handshake and a login to a public relay that is in no hurry. At five
# seconds Gmail timed out often enough to look broken.
SMTP_TIMEOUT_SECONDS = 10

_smtp_cached: tuple[datetime, CheckState] | None = None

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


async def _check_worker() -> CheckState:
    """Whether anything is consuming the queue.

    The api and the worker are separate containers that share only the database, so a deploy that
    starts the api and fails to start the worker is invisible from inside the api process. It is
    also the failure that matters most: an invitation email is a deferred job, so enrolment — the
    one flow with no way in if it fails — stops dead while every other check still answers ok.

    Three outcomes rather than two. A job finished recently is proof of life; a job waiting longer
    than the periodic cycle is proof of the opposite. An empty queue is neither, and a fresh deploy
    has an empty queue for its first few minutes — answering `fail` there would make a correct
    first boot look broken, which teaches an operator to ignore this check.
    """
    try:
        async with db.session_factory()() as session:
            finished = (
                await session.execute(
                    text(
                        "SELECT max(at) FROM procrastinate_events "
                        "WHERE type IN ('succeeded', 'failed')"
                    )
                )
            ).scalar()
            if finished is not None and now() - finished < WORKER_SILENT_AFTER:
                return "ok"

            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM procrastinate_jobs j "
                        "JOIN procrastinate_events e ON e.job_id = j.id AND e.type = 'deferred' "
                        "WHERE j.status = 'todo' AND e.at < now() - interval '15 minutes'"
                    )
                )
            ).scalar_one()
            if waiting:
                log.warning("worker readiness: %s job(s) waiting with nothing consuming", waiting)
                return "fail"

            return "ok" if finished is not None else "skipped"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        log.warning("worker readiness check failed: %s", exc)
        return "fail"


def _smtp_connect(settings: Settings) -> None:
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
    ) as client:
        client.ehlo()
        if settings.smtp_user:
            # Only meaningful once the relay has been told who we are: a relay that accepts the
            # connection and rejects the credential is the configuration that sends nothing.
            client.starttls()
            client.ehlo()
            client.login(settings.smtp_user, settings.smtp_password.get_secret_value())


async def _check_smtp(settings: Settings) -> CheckState:
    """Whether the mail relay accepts us.

    Wrong SMTP credentials produce a deployment that answers `ready`, accepts reports, and tells
    nobody anything — including the students it never invited (production-readiness.md §1.2, §1.3).
    That is the failure this exists to catch, and it is a property of the configuration: it will
    not fix itself, and it should stop a deploy.

    A relay that times out or drops the connection is a different thing. It says the relay was busy
    for ten seconds, not that this deployment cannot send mail, and treating the two alike made the
    check report `fail` on a deployment whose credentials were provably good — an amber light that
    comes on by itself is one people learn to ignore. So a rejected credential fails, and anything
    transient is `skipped`: recorded in the log, visible in the response, and not a reason to call
    the deployment unready.
    """
    global _smtp_cached
    at = now()
    if _smtp_cached is not None and at - _smtp_cached[0] < SMTP_CHECK_TTL:
        return _smtp_cached[1]

    state: CheckState
    try:
        await asyncio.to_thread(_smtp_connect, settings)
        state = "ok"
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError) as exc:
        # The relay answered and refused us. No amount of waiting changes that.
        log.error("smtp readiness: the relay rejected our credentials: %s", exc)
        state = "fail"
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("smtp readiness: could not reach the relay this time: %s", exc)
        state = "skipped"
    _smtp_cached = (at, state)
    return state


@router.get("/readyz", summary="Readiness", response_model=Readiness)
async def readyz(request: Request, response: Response) -> Readiness:
    settings: Settings = request.app.state.settings
    checks: dict[str, CheckState] = {
        "database": await _check_database(),
        "object_storage": await _check_object_storage(settings),
        "worker": await _check_worker(),
        "smtp": await _check_smtp(settings),
    }
    # `skipped` is not `ok`, but it is not a failure either: it is a check that had nothing to
    # read yet. Only `fail` — something known to be wrong — makes the deployment unready.
    ready = all(state != "fail" for state in checks.values())
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
