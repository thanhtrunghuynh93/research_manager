"""`GET /reports`: the submitted weekly reports a caller may see, filtered and paged (UI-01, UI-04).

The week is 14-20 September 2026 in Asia/Ho_Chi_Minh, due Sunday 20 at 23:59 local — 16:59 UTC.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.models import AssessmentReview, AssessmentVersion, ReviewState
from app.core.authz import Scope
from app.core.types import Role
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.reporting import service
from tests.factories import (
    WEEK_END,
    Week,
    login,
    make_entry,
    make_user,
    make_week,
    make_workspace,
    submit,
)

pytestmark = pytest.mark.module

ON_TIME = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
LATE = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)


async def _reports(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/reports", params=params)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


async def _two_students(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> Week:
    """Both students on two projects; A submits on time, B only drafts."""
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a, student_b], projects=2)
    await submit(db, student_a, week)
    b_scope = await identity_service.scope_for(db, student_b)
    await service.save_draft(db, b_scope, period_id=week.period.id, content={"half": "typed"})
    return week


async def test_the_professor_sees_every_submitted_report_and_no_draft(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    week = await _two_students(db, prof_scope, student_a, student_b, frozen_now)
    await login(client, prof)

    rows = await _reports(client)

    assert [row["student_id"] for row in rows] == [str(student_a.id)]
    row = rows[0]
    assert row["student_name"] == student_a.display_name
    assert row["period_id"] == str(week.period.id)
    assert row["local_start"] == "2026-09-14"
    assert row["local_end"] == str(WEEK_END)
    assert row["workflow_state"] == "submitted"
    assert row["version_count"] == 1
    assert row["late"] is False
    assert row["first_submitted_at"] == row["last_submitted_at"]
    assert [project["title"] for project in row["projects"]] == ["Project 0", "Project 1"]
    assert all(project["assessment"] is None for project in row["projects"])


async def test_a_student_sees_only_their_own(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    week = await _two_students(db, prof_scope, student_a, student_b, frozen_now)
    await submit(db, student_b, week)

    await login(client, student_b)
    assert [row["student_id"] for row in await _reports(client)] == [str(student_b.id)]
    # Asking for someone else's is an empty list, not theirs.
    assert await _reports(client, student_id=str(student_a.id)) == []


async def test_another_workspaces_reports_are_invisible(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a])
    await submit(db, student_a, week)

    elsewhere = await make_workspace(db, name="Other Lab")
    other_prof = await make_user(db, elsewhere, role=Role.PROF, email="other-prof@example.edu")
    other_student = await make_user(db, elsewhere, email="other-student@example.edu")
    other_week = await make_week(
        db, await identity_service.scope_for(db, other_prof), [other_student]
    )
    await submit(db, other_student, other_week)

    await login(client, prof)
    assert [row["student_id"] for row in await _reports(client)] == [str(student_a.id)]
    await login(client, other_prof)
    assert [row["student_id"] for row in await _reports(client)] == [str(other_student.id)]


async def test_each_filter_narrows_the_list(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a, student_b], projects=2)
    first, second = week.projects
    await submit(db, student_a, week)
    # B is on both projects but excused from the second, so B's package carries only the first.
    obligations = await service.list_obligations(
        db, prof_scope, week.period.id, student_id=student_b.id
    )
    for obligation in obligations:
        if obligation.project_id == second.id:
            await service.excuse_obligation(db, prof_scope, obligation.id, reason="On leave")
    await submit(db, student_b, week, make_entry(first.id))
    report_b = await service.get_report(
        db, prof_scope, period_id=week.period.id, student_id=student_b.id
    )
    await service.mark_reviewed(db, prof_scope, report_id=report_b.id)

    # A second week, which only A reports on.
    frozen_now(ON_TIME + timedelta(days=7))
    later = (await service.ensure_periods(db, prof_scope, through=WEEK_END + timedelta(days=7)))[1]
    await service.ensure_obligations(db, prof_scope, later.id)
    a_scope = await identity_service.scope_for(db, student_a)
    await service.submit_report(
        db,
        a_scope,
        period_id=later.id,
        entries=[make_entry(project.id) for project in week.projects],
    )

    await login(client, prof)

    def who(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
        return [(row["student_name"], row["local_start"]) for row in rows]

    a, b = student_a.display_name, student_b.display_name
    # Newest week first, then by name.
    assert who(await _reports(client)) == [
        (a, "2026-09-21"),
        (a, "2026-09-14"),
        (b, "2026-09-14"),
    ]
    assert who(await _reports(client, period_id=str(week.period.id))) == [
        (a, "2026-09-14"),
        (b, "2026-09-14"),
    ]
    assert who(await _reports(client, student_id=str(student_b.id))) == [(b, "2026-09-14")]
    assert who(await _reports(client, project_id=str(second.id))) == [
        (a, "2026-09-21"),
        (a, "2026-09-14"),
    ]
    assert who(await _reports(client, state="reviewed")) == [(b, "2026-09-14")]
    assert len(await _reports(client, state=["reviewed", "submitted"])) == 3
    assert who(await _reports(client, needs_review="true")) == [
        (a, "2026-09-21"),
        (a, "2026-09-14"),
    ]
    # Asking for reviewed reports that need review is a contradiction, and an empty list.
    assert await _reports(client, needs_review="true", state="reviewed") == []


async def test_needs_review_keeps_resubmissions_and_drops_revision_requests(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a, student_b])
    await submit(db, student_a, week)
    await submit(db, student_b, week)
    for student in (student_a, student_b):
        report = await service.get_report(
            db, prof_scope, period_id=week.period.id, student_id=student.id
        )
        await service.request_revision(db, prof_scope, report_id=report.id, reason="Say more")
    # A answers the request; B has not yet.
    await submit(db, student_a, week, make_entry(week.project.id, work="Said more"))

    await login(client, prof)
    rows = await _reports(client, needs_review="true")

    assert [(row["student_id"], row["workflow_state"]) for row in rows] == [
        (str(student_a.id), "resubmitted")
    ]
    assert rows[0]["version_count"] == 2
    assert rows[0]["last_submitted_at"] > rows[0]["first_submitted_at"]


async def test_late_is_judged_against_grace_and_extensions(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
    frozen_now: Callable[[datetime], None],
) -> None:
    students = [
        await make_user(db, workspace, display_name=name, email=f"{name.lower()}@example.edu")
        for name in ("Early", "Late", "Extended")
    ]
    early, late, extended = students
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, students)
    await submit(db, early, week)
    for obligation in await service.list_obligations(
        db, prof_scope, week.period.id, student_id=extended.id
    ):
        await service.extend_obligation(
            db, prof_scope, obligation.id, until=LATE + timedelta(days=1), reason="Conference"
        )

    frozen_now(LATE)
    await submit(db, late, week)
    await submit(db, extended, week)

    await login(client, prof)
    late_by_name = {row["student_name"]: row["late"] for row in await _reports(client)}

    assert late_by_name == {"Early": False, "Extended": False, "Late": True}


async def test_an_extension_granted_after_the_fact_clears_the_late_flag(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    """REP-06: an extended obligation is not a late report, whenever the extension was recorded."""
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a])
    frozen_now(LATE)
    await submit(db, student_a, week)
    await login(client, prof)
    assert [row["late"] for row in await _reports(client)] == [True]

    for obligation in await service.list_obligations(db, prof_scope, week.period.id):
        await service.extend_obligation(
            db, prof_scope, obligation.id, until=LATE + timedelta(hours=1), reason="Sick"
        )

    assert [row["late"] for row in await _reports(client)] == [False]


async def test_the_cursor_walks_every_row_once_in_order(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
    frozen_now: Callable[[datetime], None],
) -> None:
    # Two students share a name, so the order has to fall through to the id.
    students = [
        await make_user(db, workspace, display_name=name) for name in ("Bao", "An", "Bao", "Chi")
    ]
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, students)
    for student in students:
        await submit(db, student, week)
    await login(client, prof)

    everything = await _reports(client)
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/api/v1/reports", params=params)).json()
        seen.extend(row["report_id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [row["report_id"] for row in everything]
    assert len(set(seen)) == 4
    assert [row["student_name"] for row in everything] == ["An", "Bao", "Bao", "Chi"]


async def test_a_malformed_cursor_is_a_client_error(
    client: AsyncClient, prof: identity_models.User
) -> None:
    await login(client, prof)

    response = await client.get("/api/v1/reports", params={"cursor": "bm90IGpzb24="})

    assert response.status_code == 422


async def test_each_project_links_to_its_latest_assessment(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    """The professor is linked to the newest draft; the student only ever to a published one."""
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, [student_a], projects=2)
    await submit(db, student_a, week)
    first, second = week.projects

    async def assess(project_id: Any, version_no: int, state: ReviewState) -> AssessmentVersion:
        version = AssessmentVersion(
            workspace_id=prof_scope.workspace_id,
            student_id=student_a.id,
            project_id=project_id,
            period_id=week.period.id,
            version_no=version_no,
            ratings={},
            coverage_pct=100,
            confidence="high",
            confidence_reasons=[],
            narrative={},
            prompt_versions={},
        )
        db.add(version)
        await db.flush()
        db.add(
            AssessmentReview(
                workspace_id=prof_scope.workspace_id, assessment_version_id=version.id, state=state
            )
        )
        await db.flush()
        return version

    approved = await assess(first.id, 1, ReviewState.APPROVED)
    redraft = await assess(first.id, 2, ReviewState.DRAFT)

    await login(client, prof)
    links = {
        project["title"]: project["assessment"]
        for project in (await _reports(client))[0]["projects"]
    }
    assert links == {
        first.title: {"assessment_id": str(redraft.id), "status": "draft"},
        second.title: None,
    }

    await login(client, student_a)
    links = {
        project["title"]: project["assessment"]
        for project in (await _reports(client))[0]["projects"]
    }
    assert links[first.title] == {"assessment_id": str(approved.id), "status": "approved"}


async def test_a_page_costs_the_same_queries_however_many_rows_it_has(
    db: AsyncSession,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
    frozen_now: Callable[[datetime], None],
) -> None:
    """No query per row: one report and five cost the same."""
    from app.assessment import service as assessment_service

    students = [await make_user(db, workspace) for _ in range(5)]
    frozen_now(ON_TIME)
    week = await make_week(db, prof_scope, students, projects=2)
    for student in students:
        await submit(db, student, week)

    async def count(limit: int) -> int:
        statements: list[str] = []
        connection = (await db.connection()).sync_connection
        assert connection is not None

        def record(*args: Any) -> None:
            statements.append(args[2])

        event.listen(connection, "before_cursor_execute", record)
        try:
            page = await service.list_submitted_reports(db, prof_scope, limit=limit)
            await assessment_service.with_assessments(db, prof_scope, page)
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert len(page.items) == limit
        return len(statements)

    # Rows, projects, titles, obligations, calendars, assessments; reviews make seven if any exist.
    assert await count(1) == await count(5) == 6
