from __future__ import annotations

import pytest
from httpx import AsyncClient


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
    response = await client.get("/api/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("path", ["/api/v1/does-not-exist"])
async def test_unknown_route_is_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 404
