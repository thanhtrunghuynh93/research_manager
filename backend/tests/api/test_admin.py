"""The operations surface: budgets, spend, sync health, and manual retry (architecture §12).

Every route here is the professor's alone. The student-facing consequence of a stalled worker or a
spent budget is a missing assessment, so the professor needs to see the cause without a shell.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import cost
from app.identity import models as identity_models
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.api


async def _login(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def test_a_student_may_not_read_the_ai_spend(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _login(client, student_a)

    response = await client.get("/api/v1/admin/ai/usage")

    assert response.status_code == 403


async def test_the_professor_reads_this_month_s_spend(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    workspace: identity_models.Workspace,
) -> None:
    await cost.record_call(
        db,
        workspace_id=workspace.id,
        prompt_id="rate_rubric",
        prompt_version="v1",
        model="gpt-4.1",
        tokens_in=1_000_000,
        tokens_out=0,
    )
    await _login(client, prof)

    response = await client.get("/api/v1/admin/ai/usage")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["calls"] == 1
    assert body["tokens_in"] == 1_000_000
    assert body["cost_usd"] == "2.000000"


async def test_the_professor_sets_and_reads_back_a_budget(
    client: AsyncClient, prof: identity_models.User
) -> None:
    await _login(client, prof)

    written = await client.put(
        "/api/v1/admin/ai/budgets", json={"monthly_usd": "25.00", "project_monthly_usd": {}}
    )
    assert written.status_code == 200, written.text

    read_back = await client.get("/api/v1/admin/ai/budgets")
    assert read_back.json()["monthly_usd"] == "25.00"


async def test_the_budget_endpoint_reports_whether_analysis_is_currently_delayed(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    workspace: identity_models.Workspace,
) -> None:
    """Requirements §11: the delayed state must be visible, not inferred from silence."""
    await _login(client, prof)
    await client.put("/api/v1/admin/ai/budgets", json={"monthly_usd": "1.00"})
    await cost.record_call(
        db,
        workspace_id=workspace.id,
        prompt_id="rate_rubric",
        prompt_version="v1",
        model="gpt-4.1",
        tokens_in=1_000_000,
        tokens_out=0,
    )

    response = await client.get("/api/v1/admin/ai/budgets")

    assert response.json()["analysis_delayed"] is True
    assert "budget" in response.json()["reason"]


async def test_a_student_may_not_read_the_sync_health(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _login(client, student_a)

    assert (await client.get("/api/v1/admin/sync")).status_code == 403


async def test_sync_health_is_empty_rather_than_absent_without_repositories(
    client: AsyncClient, prof: identity_models.User
) -> None:
    """REPO-01: the product is fully usable without a repository, including this screen."""
    await _login(client, prof)

    response = await client.get("/api/v1/admin/sync")

    assert response.status_code == 200
    assert response.json() == []
