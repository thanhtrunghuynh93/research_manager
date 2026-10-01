"""Liveness, readiness, and who may read the gauges.

`/metrics` lives under `/api`, which the reverse proxy publishes wholesale, so it is the app's own
job to say who may read it — the gauges name every workspace's queue depth and sync staleness.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    # Nothing in the test setup fails: no worker has run yet and no relay answers, and both of
    # those are `skipped`, which is not a reason to call the deployment unready.
    assert response.status_code == 200
    assert body["status"] == "ready"


async def test_readyz_reports_the_worker_and_smtp(client: AsyncClient) -> None:
    """production-readiness.md §1.2: readiness covered the database and object storage only.

    An invitation email is a deferred job, so a deploy with a dead worker or wrong SMTP credentials
    answered `ready` and enrolled nobody — and enrolment is the one flow with no way in if it
    fails.
    """
    response = await client.get("/api/readyz")
    checks = response.json()["checks"]
    assert "worker" in checks
    assert "smtp" in checks


async def test_an_empty_queue_is_not_a_dead_worker(client: AsyncClient) -> None:
    """A fresh deploy has an empty queue for its first few minutes.

    Answering `fail` there would make a correct first boot look broken, which is how an operator
    learns to ignore a check.
    """
    response = await client.get("/api/readyz")

    assert response.json()["checks"]["worker"] in ("ok", "skipped")


async def test_rejected_credentials_make_the_deployment_unready(
    client: AsyncClient,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """The relay answered and refused us: the configuration is wrong and waiting will not fix it."""
    import smtplib

    from app.api.v1 import health

    def _reject(_: object) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    monkeypatch.setattr(health, "_smtp_connect", _reject)
    monkeypatch.setattr(health, "_smtp_cached", None)

    response = await client.get("/api/readyz")

    assert response.json()["checks"]["smtp"] == "fail"
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


async def test_a_busy_relay_does_not_make_the_deployment_unready(
    client: AsyncClient,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """A timeout says the relay was busy for ten seconds, not that this deployment cannot send.

    Treating the two alike made readiness flap between ok and fail against a relay whose
    credentials were provably good, and an amber light that comes on by itself is one people learn
    to ignore.
    """
    import smtplib

    from app.api.v1 import health

    def _timeout(_: object) -> None:
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed: read timed out")

    monkeypatch.setattr(health, "_smtp_connect", _timeout)
    monkeypatch.setattr(health, "_smtp_cached", None)

    response = await client.get("/api/readyz")

    assert response.json()["checks"]["smtp"] == "skipped"
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_the_smtp_result_is_reused_between_polls(
    client: AsyncClient,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """A relay is a third party with an opinion about how often it may be connected to."""
    from app.api.v1 import health

    calls = []

    def _count(settings: object) -> None:
        calls.append(settings)

    monkeypatch.setattr(health, "_smtp_connect", _count)
    monkeypatch.setattr(health, "_smtp_cached", None)

    for _ in range(2):
        assert (await client.get("/api/readyz")).json()["checks"]["smtp"] == "ok"
    assert len(calls) == 1


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


@pytest.fixture
def unthrottled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with no recent refresh; monkeypatch puts the module state back after."""
    from app.api.v1 import health

    monkeypatch.setattr(health, "_last_refresh", None)


def _gauge(exposed: str, series: str) -> float:
    for line in exposed.splitlines():
        if line.startswith(series + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{series} not exposed")


async def test_a_scrape_reads_the_gauges_from_the_database(
    settings: Settings, db: AsyncSession, unthrottled: None
) -> None:
    """The regression: the gauges were filled by `queue_health` in the worker's memory.

    The api is a different container, so a plain scrape served zeros. The scrape must read the
    database itself — and, unlike `?fresh=1` was, without the caller having to ask for it.
    """
    configured = settings.model_copy(update={"metrics_token": SecretStr("scrape-me")})
    await db.execute(
        text(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, status) "
            "VALUES ('default', 'tests.waiting', 'todo')"
        )
    )
    expected = (
        await db.execute(text("SELECT count(*) FROM procrastinate_jobs WHERE status = 'todo'"))
    ).scalar_one()

    async with await _client_with(configured, db) as http:
        response = await http.get("/api/metrics", headers={"Authorization": "Bearer scrape-me"})

    assert response.status_code == 200
    assert _gauge(response.text, 'rm_queue_depth{status="todo"}') == expected >= 1


async def test_the_refresh_is_rate_limited(unthrottled: None) -> None:
    """Every scrape refreshes, so a scrape loop must not become a load on the database."""
    from app.api.v1 import health

    assert health._refresh_allowed() is True
    assert health._refresh_allowed() is False


@pytest.mark.parametrize("path", ["/api/v1/does-not-exist"])
async def test_unknown_route_is_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 404
