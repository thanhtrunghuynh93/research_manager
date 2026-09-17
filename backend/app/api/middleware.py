"""Request id propagation, access log, security headers, and the authentication rate limit."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.context import bind_request_id, current_request_id, reset_request_id

access_log = logging.getLogger("app.access")
log = logging.getLogger(__name__)


# The three unauthenticated paths that do work on a caller's behalf, with a window in seconds and
# the number of requests allowed in it, per client address (production-readiness.md §2.2).
#
# The tokens themselves are 32-byte random values and are not worth guessing, so these limits are
# aimed at the two things that are: password brute-force against login, and using the reset
# endpoint to flood a known mailbox. Both limits are far above what a person doing the thing
# honestly would ever reach — a student mistyping a password five times in a minute is unaffected.
def auth_rate_limits() -> dict[str, tuple[int, int]]:
    """Read at construction rather than at import, so a test can build an app with its own cap.

    Only the login cap is configurable, and only downward in practice: the end-to-end suite signs
    in as several people from one address and would otherwise be throttled by a defence it is not
    testing. The reset and invitation limits guard a mailbox rather than a password and no caller
    needs them relaxed.
    """
    return {
        "/api/v1/auth/login": (300, get_settings().auth_login_attempts),
        "/api/v1/auth/password-reset": (3600, 5),
        "/api/v1/auth/accept-invitation": (3600, 10),
    }


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid4().hex
        token = bind_request_id(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = rid
        access_log.info(
            "%s %s -> %s in %.1f ms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            extra={"request_id": rid},
        )
        return response


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """A per-address cap on the three unauthenticated authentication paths.

    Deliberately in the application rather than at the edge, which is where
    production-readiness.md §2.2 proposed it: Caddy has no rate limiter in core, so an edge limit
    would mean building Caddy with a third-party module and carrying that in the release. This
    costs one middleware, is covered by the ordinary test suite, and keeps working whatever ends
    up in front of it.

    The counters live in this process, so the limit is per api container rather than per
    deployment. With the single-VPS topology (architecture §3) those are the same thing; if the api
    is ever scaled out, this becomes a shared counter in Postgres or Redis rather than a rewrite.

    The client address comes from `request.client.host`, which uvicorn has already resolved from
    `X-Forwarded-For` — the api runs with `--proxy-headers` behind Caddy, which sets that header
    itself. A limit keyed on a spoofable value is worth no more than the proxy in front of it.
    """

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hits: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._limits = auth_rate_limits()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limit = self._limits.get(request.url.path)
        if limit is None or request.method != "POST":
            return await call_next(request)

        window, allowed = limit
        client = request.client.host if request.client else "unknown"
        key = (client, request.url.path)
        at = time.monotonic()

        recent = [seen for seen in self._hits[key] if at - seen < window]
        if len(recent) >= allowed:
            self._hits[key] = recent
            retry_after = int(window - (at - recent[0])) + 1
            # Logged at warning because a client that reaches this is either under attack or
            # broken, and both are worth seeing. The address is an operational fact, not a person.
            log.warning("rate limit reached for %s on %s", client, request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": "Too many attempts. Wait and try again.",
                },
                headers={"Retry-After": str(retry_after)},
            )

        recent.append(at)
        self._hits[key] = recent
        self._prune(at)
        return await call_next(request)

    def _prune(self, at: float) -> None:
        """Drop addresses with nothing recent, so the table cannot grow without bound.

        Without this the dictionary is a slow memory leak keyed by anything that ever sent one
        request — which, on a public address, is a way to grow it on purpose.
        """
        if len(self._hits) < 1024:
            return
        longest = max(window for window, _ in self._limits.values())
        self._hits = defaultdict(
            list,
            {
                key: seen
                for key, hits in self._hits.items()
                if (seen := [one for one in hits if at - one < longest])
            },
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response
