"""REP-01/REP-06: the reporting calendar, generated periods, and per-membership obligations.

The deadline is fixed by rule — 23:59 local on the day before the weekly meeting — and the meeting
follows the period it discusses. With the proposed default (week Monday–Sunday, meeting Monday) a
period covering Mon 14 to Sun 20 September is discussed on Mon 21 and is due Sun 20 at 23:59.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError, NotFoundError
from app.identity import models as identity_models
from app.projects import service as projects_service
from app.reporting import models, service

pytestmark = pytest.mark.module

TZ = "Asia/Ho_Chi_Minh"  # UTC+7, no daylight saving
MONDAY, SUNDAY = 0, 6


async def _calendar(db: AsyncSession, scope: Scope, **overrides: object) -> object:
    return await service.configure_calendar(
        db,
        scope,
        timezone=TZ,
        meeting_weekday=MONDAY,
        week_start_weekday=MONDAY,
        effective_from=date(2026, 9, 14),
        **overrides,
    )


async def test_periods_run_from_the_configured_week_start(
    db: AsyncSession, prof_scope: Scope
) -> None:
    await _calendar(db, prof_scope)

    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))

    assert periods[0].local_start == date(2026, 9, 14)  # Monday
    assert periods[0].local_end == date(2026, 9, 20)  # Sunday
    assert periods[1].local_start == date(2026, 9, 21), "periods are contiguous"


async def test_the_meeting_follows_the_period_and_fixes_the_deadline(
    db: AsyncSession, prof_scope: Scope
) -> None:
    await _calendar(db, prof_scope)

    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]

    assert period.meeting_date == date(2026, 9, 21), "the Monday after the reported week"
    # 23:59 local on Sunday 20 September = 16:59 UTC.
    assert period.deadline_utc == datetime(2026, 9, 20, 16, 59, tzinfo=UTC)
    assert period.reminder_due_utc == datetime(2026, 9, 20, 17, 0, tzinfo=UTC)  # 00:00 local


async def test_generating_periods_twice_creates_nothing_new(
    db: AsyncSession, prof_scope: Scope
) -> None:
    await _calendar(db, prof_scope)
    first = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))

    second = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))

    assert [p.id for p in first] == [p.id for p in second]


async def test_changing_the_meeting_day_applies_to_future_periods_only(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REP-01: periods already open keep their original deadline.
    await _calendar(db, prof_scope)
    existing = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 27)))[0]
    original_deadline = existing.deadline_utc

    await _calendar(db, prof_scope, meeting_weekday=2, effective_from=date(2026, 10, 5))
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 18))

    unchanged = next(p for p in periods if p.local_start == existing.local_start)
    assert unchanged.deadline_utc == original_deadline

    later = next(p for p in periods if p.local_start == date(2026, 10, 5))
    assert later.meeting_date == date(2026, 10, 14), "Wednesday after the reported week"
    assert later.deadline_utc == datetime(2026, 10, 13, 16, 59, tzinfo=UTC)


async def test_only_the_professor_configures_the_calendar(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    with pytest.raises(ForbiddenError):
        await _calendar(db, student_a_scope)


async def test_obligations_follow_membership_dates(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 21)
    )
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))

    obligations = await service.ensure_obligations(db, prof_scope, periods[0].id)
    later = await service.ensure_obligations(db, prof_scope, periods[1].id)

    assert obligations == [], "the student had not joined during the first week"
    assert [o.student_id for o in later] == [student_a.id]


async def test_a_paused_project_owes_no_report(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-06: paused projects are an exceptional week, not a missing report.
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]

    await projects_service.update_project(db, prof_scope, project.id, status="paused")
    obligations = await service.ensure_obligations(db, prof_scope, period.id)

    assert obligations == []


async def test_a_departed_student_owes_nothing_for_later_weeks(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    membership = await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))
    await projects_service.end_membership(
        db, prof_scope, membership.id, left_on=date(2026, 9, 21)
    )

    first = await service.ensure_obligations(db, prof_scope, periods[0].id)
    second = await service.ensure_obligations(db, prof_scope, periods[1].id)

    assert [o.student_id for o in first] == [student_a.id], "the week they worked still counts"
    assert second == []


async def test_an_exemption_records_its_reason_and_no_report_is_owed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-06: record leave, holidays, and extensions; do not invent a missing report.
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    obligation = (await service.ensure_obligations(db, prof_scope, period.id))[0]

    excused = await service.excuse_obligation(
        db, prof_scope, obligation.id, reason="Approved leave: family event"
    )

    assert excused.state is models.ObligationState.EXCUSED
    assert excused.excuse_reason == "Approved leave: family event"


async def test_an_extension_moves_the_effective_deadline_for_one_obligation(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    obligation = (await service.ensure_obligations(db, prof_scope, period.id))[0]
    extended_to = period.deadline_utc + timedelta(days=2)

    extended = await service.extend_obligation(
        db, prof_scope, obligation.id, until=extended_to, reason="Cluster outage"
    )

    assert extended.extension_until_utc == extended_to
    assert extended.state is models.ObligationState.REQUIRED, "an extension is not an exemption"


async def test_a_student_cannot_excuse_themselves(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    obligation = (await service.ensure_obligations(db, prof_scope, period.id))[0]

    with pytest.raises(ForbiddenError):
        await service.excuse_obligation(db, student_a_scope, obligation.id, reason="Busy")


async def test_periods_cannot_be_generated_without_a_calendar(
    db: AsyncSession, prof_scope: Scope
) -> None:
    with pytest.raises(NotFoundError):
        await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))
