"""UI-07: in-app notifications, their visibility, and what a user may mute."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.types import Role
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.notifications import service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _period_and_project(db: AsyncSession, prof_scope: Scope, student: identity_models.User):
    await reporting_service.configure_calendar(
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
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def test_submitting_a_report_notifies_the_professor(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _period_and_project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[{"project_id": project.id, "stage": "implementation", "work_performed": "Did it"}],
    )

    notifications = await service.list_notifications(db, prof_scope)
    assert [n.kind for n in notifications] == [service.REPORT_SUBMITTED]
    assert notifications[0].recipient_id == prof.id


async def test_a_student_sees_only_their_own_notifications(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.REVISION_REQUESTED,
        subject_table="weekly_reports",
        subject_id=student_a.id,
        payload={"reason": "Name the baseline"},
    )
    scope_b = await identity_service.scope_for(db, student_b)

    assert await service.list_notifications(db, scope_b) == []
    scope_a = await identity_service.scope_for(db, student_a)
    assert len(await service.list_notifications(db, scope_a)) == 1


async def test_a_notification_can_be_marked_read_once(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    created = await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.REVISION_REQUESTED,
        subject_table="weekly_reports",
        subject_id=student_a.id,
        payload={},
    )
    assert created is not None
    scope = await identity_service.scope_for(db, student_a)

    read = await service.mark_read(db, scope, created.id)

    assert read.read_at is not None
    assert (await service.unread_count(db, scope)) == 0


async def test_a_student_cannot_read_someone_elses_notification(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    created = await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.REVISION_REQUESTED,
        subject_table="weekly_reports",
        subject_id=student_a.id,
        payload={},
    )
    assert created is not None
    scope_b = await identity_service.scope_for(db, student_b)

    with pytest.raises(NotFoundError):
        await service.mark_read(db, scope_b, created.id)


async def test_muting_a_category_stops_those_notifications(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    scope = await identity_service.scope_for(db, student_a)
    await service.mute(db, scope, kind=service.DEADLINE_APPROACHING)

    created = await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.DEADLINE_APPROACHING,
        subject_table="reporting_periods",
        subject_id=student_a.id,
        payload={},
    )

    assert created is None
    assert await service.list_notifications(db, scope) == []


async def test_unmuting_restores_them(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    scope = await identity_service.scope_for(db, student_a)
    await service.mute(db, scope, kind=service.DEADLINE_APPROACHING)
    await service.unmute(db, scope, kind=service.DEADLINE_APPROACHING)

    created = await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.DEADLINE_APPROACHING,
        subject_table="reporting_periods",
        subject_id=student_a.id,
        payload={},
    )

    assert created is not None


@pytest.mark.parametrize("kind", [service.MISSED_DEADLINE, service.REVISION_REQUESTED])
async def test_critical_categories_cannot_be_muted(
    db: AsyncSession, student_a: identity_models.User, kind: str
) -> None:
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ValidationError):
        await service.mute(db, scope, kind=kind)


async def test_a_user_cannot_mute_on_behalf_of_someone_else(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Preferences belong to the person they silence.
    scope = await identity_service.scope_for(db, student_a)
    await service.mute(db, scope, kind=service.DEADLINE_APPROACHING)

    preferences = await service.list_preferences(db, prof_scope)

    assert preferences == [], "the professor has muted nothing of their own"


async def test_pre_deadline_reminders_fire_once_per_offset(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-07: configurable in-app reminders before the deadline, respecting the timezone.
    period, _ = await _period_and_project(db, prof_scope, student_a)
    await service.set_reminder_offsets(db, prof_scope, offsets_hours=[48, 6])

    first = await service.dispatch_due_reminders(db, at=_hours_before(period.deadline_utc, 47))
    second = await service.dispatch_due_reminders(db, at=_hours_before(period.deadline_utc, 46))
    third = await service.dispatch_due_reminders(db, at=_hours_before(period.deadline_utc, 5))

    assert [n.kind for n in first] == ["reminder:48h"]
    assert second == [], "the same offset does not fire twice"
    assert [n.kind for n in third] == ["reminder:6h"]


def _hours_before(deadline: object, hours: int):
    from datetime import timedelta

    return deadline - timedelta(hours=hours)  # type: ignore[operator]


async def test_only_the_professor_configures_reminder_offsets(
    db: AsyncSession, student_a: identity_models.User
) -> None:
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ForbiddenError):
        await service.set_reminder_offsets(db, scope, offsets_hours=[48])


async def test_a_reminder_rule_does_not_reach_another_workspace(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-07: the offsets are one professor's decision, about their own students.

    Both reads in the dispatcher are job-level and unscoped, so matching them by time alone let
    workspace A's 48-hour rule notify workspace B's students — including a workspace whose
    professor had deliberately configured no reminders at all.
    """
    from tests.factories import make_user, make_workspace

    period, _ = await _period_and_project(db, prof_scope, student_a)
    await service.set_reminder_offsets(db, prof_scope, offsets_hours=[48])

    other = await make_workspace(db, name="Another Lab")
    other_prof = await make_user(db, other, role=Role.PROF, email="other-prof@other.edu")
    other_student = await make_user(db, other, email="other-student@other.edu")
    other_scope = await identity_service.scope_for(db, other_prof)
    await _period_and_project(db, other_scope, other_student)
    # This professor set no offsets, so their students should hear nothing before the deadline.

    raised = await service.dispatch_due_reminders(db, at=_hours_before(period.deadline_utc, 47))

    assert [n.kind for n in raised] == ["reminder:48h"]
    assert {n.recipient_id for n in raised} == {student_a.id}


async def test_a_second_revision_request_in_a_week_still_reaches_the_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-05/UI-07: a revision request is one kind a student is not allowed to mute.

    The unique index was (recipient, period, kind), so the second request of a week — another
    project, or a second round on the same one — collided with the first and was dropped without
    a trace.
    """
    period, first_project = await _period_and_project(db, prof_scope, student_a)
    second_project = await projects_service.create_project(
        db, prof_scope, title="Second study", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, second_project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, second_project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    scope = await identity_service.scope_for(db, student_a)
    submitted = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Did the work.",
                "results": "It worked.",
            }
            for project in (first_project, second_project)
        ],
    )
    report_id = (await reporting_service.get_report(db, scope, period_id=period.id)).id
    assert submitted.version_no == 1

    await reporting_service.request_revision(
        db,
        prof_scope,
        report_id=report_id,
        project_id=first_project.id,
        reason="Add the ablation numbers.",
    )
    await reporting_service.request_revision(
        db,
        prof_scope,
        report_id=report_id,
        project_id=second_project.id,
        reason="The plot axes are unlabelled.",
    )

    sent = [
        n
        for n in await service.list_notifications(db, scope)
        if n.kind == service.REVISION_REQUESTED
    ]
    assert len(sent) == 2
    assert {n.payload["project_id"] for n in sent} == {
        str(first_project.id),
        str(second_project.id),
    }
