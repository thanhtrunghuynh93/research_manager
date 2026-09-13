"""The weekly package over HTTP: one submission flow, per-entry revisions, and privacy (UI-02)."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _sign_in(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def _week(db: AsyncSession, prof_scope: Scope, student: identity_models.User) -> tuple:
    await service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, period.id)
    return period, project


def _entry(project_id: object, work: str = "Implemented the data loader") -> dict:
    return {
        "project_id": str(project_id),
        "stage": "implementation",
        "work_performed": work,
        "results": "The loader reproduces the published split sizes.",
        "next_plan": {"outcomes": ["Run the baseline end to end"]},
    }


async def test_a_student_drafts_and_submits_the_weekly_package(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, student_a)
    await _sign_in(client, student_a)

    draft = await client.patch(
        f"/api/v1/periods/{period.id}/report/draft",
        json={"content": {"entries": [{"work": "half typed"}]}},
    )
    assert draft.status_code == 200
    assert draft.json()["draft_saved_at"] is not None

    submitted = await client.post(
        f"/api/v1/periods/{period.id}/report/submit", json={"entries": [_entry(project.id)]}
    )
    assert submitted.status_code == 201
    assert submitted.json()["version_no"] == 1
    assert submitted.json()["timing_status"] in ("on_time", "late")


async def test_a_repeated_submission_with_one_key_creates_one_version(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, student_a)
    await _sign_in(client, student_a)
    body = {"entries": [_entry(project.id)]}
    headers = {"Idempotency-Key": "double-click"}

    first = await client.post(
        f"/api/v1/periods/{period.id}/report/submit", json=body, headers=headers
    )
    second = await client.post(
        f"/api/v1/periods/{period.id}/report/submit", json=body, headers=headers
    )

    assert first.json()["id"] == second.json()["id"]


async def test_a_student_cannot_read_another_students_report(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # AC-02: denied in the API as well as in search, downloads, and exports.
    period, project = await _week(db, prof_scope, student_a)
    await _sign_in(client, student_a)
    await client.post(
        f"/api/v1/periods/{period.id}/report/submit", json={"entries": [_entry(project.id)]}
    )
    await client.post("/api/v1/auth/logout")
    await _sign_in(client, student_b)

    response = await client.get(
        f"/api/v1/periods/{period.id}/report", params={"student_id": str(student_a.id)}
    )

    assert response.status_code == 404


async def test_the_professor_requests_a_revision_of_one_entry(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    period, project = await _week(db, prof_scope, student_a)
    student_scope = await identity_service.scope_for(db, student_a)
    await service.submit_report(
        db, student_scope, period_id=period.id, entries=[_entry(project.id)]
    )
    report = await service.get_report(db, prof_scope, period_id=period.id, student_id=student_a.id)
    await _sign_in(client, prof)

    response = await client.post(
        f"/api/v1/reports/{report.id}/revisions",
        json={"project_id": str(project.id), "reason": "Name the baseline you compared against"},
    )

    assert response.status_code == 201
    listed = await client.get(f"/api/v1/reports/{report.id}/revisions")
    assert [r["project_id"] for r in listed.json()] == [str(project.id)]


async def test_the_calendar_is_professor_only(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.put(
        "/api/v1/calendar",
        json={"timezone": "Asia/Ho_Chi_Minh", "effective_from": "2026-09-14"},
    )

    assert response.status_code == 403
