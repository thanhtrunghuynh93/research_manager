"""RFC 9457 problem-details responses for domain errors."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core import metrics
from app.core.context import current_request_id
from app.core.errors import DomainError

log = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"

# The request itself, rather than a field of it: a body that is not JSON at all, or a missing one.
_WHOLE_REQUEST = "the request"


def _field_of(location: tuple[object, ...] | list[object]) -> str:
    """`("body", "entries", 0, "hours")` as `entries[0].hours` — the name the caller sent.

    The first element says which part of the request the value came from (body, path, query) and
    is dropped: it is the same for every error in a given response and says nothing the field name
    does not. An index becomes a subscript so the path reads the way the payload was written.
    """
    parts = list(location)[1:]
    if not parts:
        return _WHOLE_REQUEST
    name = ""
    for part in parts:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name = f"{name}.{part}" if name else str(part)
    return name or _WHOLE_REQUEST


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

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's own validation failures, in this API's problem shape rather than its own.

        Unhandled, these are the one response in the API that is not RFC 9457: FastAPI answers
        with `{"detail": [{...}, ...]}`, an array of objects where every other refusal carries a
        string. A client that renders `detail` — as the report editor does, to show the API's own
        words — then renders an array of objects, which is how a negative number in the optional
        Hours box blanked the whole page instead of failing the field.

        `input` is deliberately not echoed. It is the caller's own value, it can be the entire
        rejected payload, and repeating it in the response body puts it in every log and proxy
        between here and the browser for no diagnostic gain the field name does not give.
        """
        fields = [
            {"field": _field_of(error.get("loc", ())), "message": str(error.get("msg", ""))}
            for error in exc.errors()
        ]
        first = fields[0] if fields else {"field": _WHOLE_REQUEST, "message": "is not valid"}
        # The first failure, and a count for the rest: naming only the first sends a caller who
        # fixes it straight back here for the second, and a request with twenty bad fields should
        # not put twenty sentences on a screen. `invalid_fields` carries all of them for a form
        # that wants to mark each input.
        detail = f"{first['field']}: {first['message']}"
        if len(fields) > 1:
            detail += f" (and {len(fields) - 1} more)"
        log.info("request validation failed: %s", fields)
        return problem(422, "Validation failed", detail, invalid_fields=fields)

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
