"""Liveness, readiness, and who may read the gauges.

`/metrics` lives under `/api`, which the reverse proxy publishes wholesale, so it is the app's own
job to say who may read it — the gauges name every workspace's queue depth and sync staleness.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app


async def test_healthz_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_readyz_checks_database(client: AsyncClient) -> None:
    response = await client.get("/api/readyz")
    body = response.json()
    assert body["checks"]["database"] == "ok"
    # object storage is not running in unit tests, so readiness is degraded, not an error
    assert response.status_code in (200, 503)
    assert body["status"] in ("ready", "degraded")


async def test_metrics_is_prometheus_text(client: AsyncClient) -> None:
    """No token configured: a development or pilot host stays scrapeable without inventing one."""
    response = await client.get("/api/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


async def _client_with(settings: Settings, db: object) -> AsyncClient:
    app = create_app(settings)

    async def _session_override() -> object:
        yield db

    app.dependency_overrides[get_session] = _session_override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_configured_token_is_required(settings: Settings, db: object) -> None:
    configured = settings.model_copy(update={"metrics_token": SecretStr("scrape-me")})

    async with await _client_with(configured, db) as http:
        assert (await http.get("/api/metrics")).status_code == 401
        assert (
            await http.get("/api/metrics", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        allowed = await http.get("/api/metrics", headers={"Authorization": "Bearer scrape-me"})

    assert allowed.status_code == 200


async def test_production_without_a_token_refuses_everybody(settings: Settings, db: object) -> None:
    """A missing token in prod is a misconfiguration; the safe reading of it is "nobody"."""
    misconfigured = settings.model_copy(update={"env": "prod", "metrics_token": SecretStr("")})

    async with await _client_with(misconfigured, db) as http:
        response = await http.get("/api/metrics")

    assert response.status_code == 401


async def test_an_on_demand_refresh_is_rate_limited() -> None:
    """`?fresh=1` runs the full query set; one operator is the use, a scrape loop is not."""
    from app.api.v1 import health

    health._last_fresh = None
    assert health._refresh_allowed() is True
    assert health._refresh_allowed() is False


@pytest.mark.parametrize("path", ["/api/v1/does-not-exist"])
async def test_unknown_route_is_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 404
