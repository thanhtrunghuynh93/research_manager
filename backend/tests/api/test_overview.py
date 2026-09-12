"""The professor overview (UI-01).

One payload behind one screen. What matters about it is the same thing that matters about the
assistant: the counts are computed, not narrated, and a gap in the evidence is labelled as a gap
rather than shown as a quiet week (AC-04).
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.api


async def _login(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def _week(
    db: AsyncSession, prof_scope: Scope, students: list[identity_models.User]
) -> tuple[object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in students:
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def test_a_student_may_not_read_the_professor_overview(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _login(client, student_a)

    assert (await client.get("/api/v1/overview")).status_code == 403


async def test_the_overview_names_the_current_week_and_its_deadline(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    await _week(db, prof_scope, [student_a])
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["current_period"]["local_start"]
    assert body["current_period"]["deadline_utc"]
    assert body["current_period"]["timezone"] == "Asia/Ho_Chi_Minh"


async def test_the_overview_counts_outstanding_obligations_from_the_table(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    period, project = await _week(db, prof_scope, [student_a, student_b])
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the baseline.",
                "results": "nDCG@10 is 0.412.",
            }
        ],
    )
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["outstanding"]["count"] == 1
    assert body["outstanding"]["as_of"]
    assert body["outstanding"]["entries"][0]["student_id"] == str(student_b.id)


async def test_the_overview_shows_an_empty_review_queue_rather_than_omitting_it(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    """A missing section reads as a broken screen; an empty one reads as nothing to do."""
    await _week(db, prof_scope, [student_a])
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["review_queue"] == []
    assert body["sync_issues"] == []
    assert body["stalled_analyses"] == []


async def test_the_overview_surfaces_a_spent_budget_as_a_named_condition(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
) -> None:
    """Requirements §11: analysis delayed by budget is a visible state, not a silent absence."""
    from app.ai import cost

    await identity_service.set_ai_budgets(db, prof_scope, {"monthly_usd": "1.00"})
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

    body = (await client.get("/api/v1/overview")).json()

    assert body["ai_budget"]["analysis_delayed"] is True
    assert "budget" in body["ai_budget"]["reason"]
