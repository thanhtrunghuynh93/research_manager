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
from app.core.clock import local_date, now
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
    # Through *today* on the workspace's calendar, not through a fixed 20 September. The week of
    # 14–20 September was the current one when this was written and stopped being it at local
    # midnight on the 21st, after which `current_period` was None and this file failed on a clock
    # rather than on a change. A test that asserts something is current has to open the week that
    # contains now.
    periods = await reporting_service.ensure_periods(
        db, prof_scope, through=local_date(now(), "Asia/Ho_Chi_Minh")
    )
    current = periods[-1]
    await reporting_service.ensure_obligations(db, prof_scope, current.id)
    return current, project


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
    # And by name: this list sits directly under a board that names everyone on it.
    assert body["outstanding"]["entries"][0]["student_name"] == student_b.display_name


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


async def test_the_overview_is_quiet_about_mail_when_nothing_has_failed(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    await _week(db, prof_scope, [student_a])
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["mail"]["warning"] is False
    assert body["mail"]["reason"] == ""


async def test_an_invitation_that_never_sent_reaches_the_overview(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
) -> None:
    """production-readiness.md §1.1: the failure used to exist only in the job queue.

    Invitation and recovery emails bypass `email_deliveries` on purpose — a token message has no
    in-app counterpart and the row would hold a live credential until the next sweep. The cost was
    that with SMTP misconfigured the job died in `procrastinate_jobs` while the roll still read
    "Invitation sent to …", and nobody learned the student was never contacted.
    """
    from sqlalchemy import text

    await db.execute(
        text(
            "INSERT INTO procrastinate_jobs (task_name, status, args, queue_name, lock) "
            "VALUES ('notifications.send_token_email', 'failed', '{}', 'default', :lock)"
        ),
        {"lock": "a-spent-invitation"},
    )
    await db.flush()
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["mail"]["warning"] is True
    assert body["mail"]["failed_token_emails"] == 1
    # Named as an enrolment that did not happen, not as a generic mail problem: the person it was
    # for has no session, no in-app message, and no other way into an invitation-only system.
    assert "cannot sign in" in body["mail"]["reason"]


async def test_the_week_lists_every_report_owed_and_which_of_them_are_in(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """UI-01: the week as a whole, not only its absences.

    `outstanding` is the same obligations read for one of their three states, and a supervisor
    cannot plan from a list of absences: a student who has reported does not appear in it at all.
    """
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

    assert len(body["week"]) == 1, "one workspace"
    board = body["week"][0]
    assert board["workspace_name"]
    # The week `_week` opened, not a date this file was written in: the board is whichever week
    # contains today, and pinning it to 14–20 September made this pass only until that week ended.
    assert (board["local_start"], board["local_end"]) == (
        period.local_start.isoformat(),
        period.local_end.isoformat(),
    )
    assert (board["submitted"], board["owed"], board["excused"]) == (1, 1, 0)

    assert [one["project_title"] for one in board["projects"]] == ["Retrieval baselines"]
    students = board["projects"][0]["students"]
    by_id = {one["student_id"]: one for one in students}
    assert by_id[str(student_a.id)]["state"] == "submitted"
    assert by_id[str(student_b.id)]["state"] == "owed"
    # The name, not eight characters of a uuid: the point of the board is to be read.
    assert by_id[str(student_a.id)]["student_name"] == student_a.display_name


async def test_an_excused_obligation_is_listed_and_marked_rather_than_counted_as_owed(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    # REP-06: leave and holidays are recorded, not treated as a missing report — so the row has to
    # be on the board saying why, rather than absent from it or amber in it.
    period, _ = await _week(db, prof_scope, [student_a])
    obligations = await reporting_service.list_obligations(db, prof_scope, period.id)
    await reporting_service.excuse_obligation(
        db, prof_scope, obligations[0].id, reason="Approved leave"
    )
    await _login(client, prof)

    board = (await client.get("/api/v1/overview")).json()["week"][0]

    assert (board["submitted"], board["owed"], board["excused"]) == (0, 0, 1)
    student = board["projects"][0]["students"][0]
    assert student["state"] == "excused"
    assert student["excuse_reason"] == "Approved leave"


async def test_a_week_with_no_obligations_yet_is_an_empty_board_rather_than_a_missing_one(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
) -> None:
    # Every section is always present: a missing one reads as a broken screen.
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    await _login(client, prof)

    body = (await client.get("/api/v1/overview")).json()

    assert body["week"] == []
