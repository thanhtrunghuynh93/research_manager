"""A per-address cap on the three unauthenticated auth paths (production-readiness.md §2.2).

The tokens themselves are 32-byte random values, so what these limits are for is password
brute-force against login and using the reset endpoint to flood a known mailbox. Neither is
stopped by anything else: Caddy adds no limiter, and the audit's suggestion of putting one at the
edge would have meant building Caddy with a third-party module.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.middleware import AUTH_RATE_LIMITS, AuthRateLimitMiddleware


@pytest.fixture(autouse=True)
def _empty_counters(client: AsyncClient) -> None:
    """Each test starts from an empty table; the middleware instance outlives one request."""
    for middleware in _limiters(client):
        middleware._hits.clear()


def _limiters(client: AsyncClient) -> list[AuthRateLimitMiddleware]:
    app = client._transport.app  # type: ignore[attr-defined]
    found = []
    while app is not None:
        if isinstance(app, AuthRateLimitMiddleware):
            found.append(app)
        app = getattr(app, "app", None)
    return found


async def test_repeated_sign_in_attempts_are_eventually_refused(client: AsyncClient) -> None:
    """The limit is well above what a person mistyping a password would ever reach."""
    _, allowed = AUTH_RATE_LIMITS["/api/v1/auth/login"]
    body = {"email": "nobody@example.org", "password": "wrong-password"}

    for _ in range(allowed):
        response = await client.post("/api/v1/auth/login", json=body)
        assert response.status_code != 429

    refused = await client.post("/api/v1/auth/login", json=body)
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    # The 429 is dressed like every other response rather than being the one bare reply we serve.
    assert refused.headers["X-Content-Type-Options"] == "nosniff"
    assert refused.headers["X-Request-ID"]


async def test_the_reset_endpoint_cannot_be_used_to_flood_a_mailbox(client: AsyncClient) -> None:
    _, allowed = AUTH_RATE_LIMITS["/api/v1/auth/password-reset"]
    body = {"email": "a-real-student@example.org"}

    for _ in range(allowed):
        assert (await client.post("/api/v1/auth/password-reset", json=body)).status_code != 429

    assert (await client.post("/api/v1/auth/password-reset", json=body)).status_code == 429


async def test_the_limit_is_per_path(client: AsyncClient) -> None:
    """Spending the login budget must not lock a student out of accepting their invitation."""
    _, allowed = AUTH_RATE_LIMITS["/api/v1/auth/login"]
    for _ in range(allowed + 1):
        await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.org", "password": "wrong"}
        )

    accepted = await client.post(
        "/api/v1/auth/accept-invitation", json={"token": "not-a-token", "password": "whatever-123"}
    )
    assert accepted.status_code != 429


async def test_ordinary_traffic_is_untouched(client: AsyncClient) -> None:
    """Only the three listed paths are limited, and only POST to them."""
    for _ in range(AUTH_RATE_LIMITS["/api/v1/auth/login"][1] + 5):
        assert (await client.get("/api/healthz")).status_code == 200
