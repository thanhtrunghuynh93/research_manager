"""RFC 9457 problem-details responses for domain errors."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core import metrics
from app.core.context import current_request_id
from app.core.errors import DomainError

log = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def problem(status: int, title: str, detail: str, **extra: object) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, **extra}
    body["request_id"] = current_request_id()
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        if exc.status_code in (401, 403):
            # Requirements §11 observability: a rise in refusals is worth seeing. The label is the
            # status and nothing else — who was refused, and for what, belongs in the audit log.
            metrics.ACCESS_DENIALS.labels(status=str(exc.status_code)).inc()
        return problem(exc.status_code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        """A constraint the database enforces and the service checked a moment too early.

        Every read-then-write guard in the services is a check against a snapshot: two concurrent
        requests both pass it and the loser meets the constraint. That is the same answer the
        caller gets sequentially, so it should read the same way — a 409, not a 500 with a stack
        trace for a double-clicked form. A net, not a substitute for the guards.
        """
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate == UNIQUE_VIOLATION:
            log.info("unique violation surfaced as a conflict: %s", exc.orig)
            return problem(409, "Conflict", "that record already exists")
        if sqlstate == FOREIGN_KEY_VIOLATION:
            log.info("foreign key violation surfaced as a validation error: %s", exc.orig)
            return problem(422, "Validation failed", "that request refers to something missing")
        log.exception("database integrity error: %s", exc)
        return problem(500, "Internal server error", "An unexpected error occurred.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", exc)
        return problem(500, "Internal server error", "An unexpected error occurred.")
