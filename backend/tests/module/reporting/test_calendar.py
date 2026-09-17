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
from app.core.clock import now
from app.core.errors import ForbiddenError, NotFoundError
from app.identity import models as identity_models
from app.projects import service as projects_service
from app.reporting import models, service

pytestmark = pytest.mark.module

TZ = "Asia/Ho_Chi_Minh"  # UTC+7, no daylight saving
MONDAY, SUNDAY = 0, 6


async def _calendar(db: AsyncSession, scope: Scope, **overrides: object) -> object:
    params: dict[str, object] = {
        "timezone": TZ,
        "meeting_weekday": MONDAY,
        "week_start_weekday": MONDAY,
        "effective_from": date(2026, 9, 14),
    }
    params.update(overrides)
    return await service.configure_calendar(db, scope, **params)  # type: ignore[arg-type]


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
    await projects_service.end_membership(db, prof_scope, membership.id, left_on=date(2026, 9, 21))

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


async def test_freezing_carries_the_previous_weeks_plan_into_the_new_baseline(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # PROJ-04: next-week plans submitted in the previous report become the next baseline.
    from app.identity import service as identity_service
    from app.projects import service as projects_service

    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 10, 4))
    await service.ensure_obligations(db, prof_scope, periods[0].id)
    student_scope = await identity_service.scope_for(db, student_a)
    await service.submit_report(
        db,
        student_scope,
        period_id=periods[0].id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Built the loader",
                "next_plan": {
                    "items": [
                        {"planned_outcome": "Run the baseline end to end", "weight": 2},
                        {"planned_outcome": "Draft the method section", "weight": 1},
                    ]
                },
            }
        ],
    )

    await service.ensure_obligations(db, prof_scope, periods[1].id)
    baselines = await service.freeze_baselines(db, prof_scope, periods[1].id)

    assert len(baselines) == 1
    assert baselines[0].state.value == "frozen"
    assert [item.planned_outcome for item in baselines[0].items] == [
        "Run the baseline end to end",
        "Draft the method section",
    ]


async def test_freezing_with_no_previous_plan_records_an_empty_baseline(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-18: a new member has no previous report, so there is nothing to freeze.
    from app.projects import service as projects_service

    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, period.id)

    baselines = await service.freeze_baselines(db, prof_scope, period.id)

    assert [b.state.value for b in baselines] == ["empty"]


async def test_freezing_twice_changes_nothing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    from app.projects import service as projects_service

    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, period.id)

    first = await service.freeze_baselines(db, prof_scope, period.id)
    second = await service.freeze_baselines(db, prof_scope, period.id)

    assert [b.id for b in first] == [b.id for b in second]


# ------------------------------------------------------------------ reading the calendar back


async def test_the_current_calendar_is_absent_before_it_is_configured(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """Absent is a state, not an error: a screen has to tell it from "configured"."""
    assert await service.current_calendar(db, prof_scope) is None


async def test_the_current_calendar_is_the_latest_version(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """Configuring writes a new version rather than editing one, so the read follows the newest."""
    await _calendar(db, prof_scope)
    second = await _calendar(db, prof_scope, meeting_weekday=2, effective_from=date(2026, 10, 5))

    current = await service.current_calendar(db, prof_scope)

    assert current is not None
    assert current.version == second.version
    assert current.meeting_weekday == 2


async def test_a_student_may_read_the_calendar(
    db: AsyncSession, prof_scope: Scope, student_a_scope: Scope
) -> None:
    """REP-01: everyone needs to know when their report is due, so this is not prof-only."""
    await _calendar(db, prof_scope)

    current = await service.current_calendar(db, student_a_scope)

    assert current is not None and current.timezone == TZ


async def test_a_student_who_starts_a_project_owes_a_report_without_the_professor(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_a_scope: Scope,
) -> None:
    """PROJ-07, and the point of the whole change: the chain closes without a professor in it.

    The calendar is anchored so the current period began three days ago whatever today's weekday
    is, rather than to a fixed date — the rule under test is about joining part-way through a week,
    so the test must not depend on which day it is run.
    """
    today = now().date()
    started = today - timedelta(days=3)
    await _calendar(db, prof_scope, effective_from=started, week_start_weekday=started.weekday())
    await projects_service.create_project(db, student_a_scope, title="Mine", stage="implementation")
    periods = await service.ensure_periods(db, prof_scope, through=today + timedelta(days=10))

    this_week = await service.ensure_obligations(db, prof_scope, periods[0].id)
    next_week = await service.ensure_obligations(db, prof_scope, periods[1].id)

    assert this_week == [], "the week was already running when they started the project"
    assert [o.student_id for o in next_week] == [student_a.id]


async def test_joining_mid_week_does_not_owe_the_week_that_is_ending(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_a_scope: Scope,
) -> None:
    # Otherwise a student who joins on a Saturday is late by Sunday night, for a week they were
    # not on the project for — a missed-deadline email they caused by joining.
    today = now().date()
    started = today - timedelta(days=3)
    await _calendar(db, prof_scope, effective_from=started, week_start_weekday=started.weekday())
    project = await projects_service.create_project(
        db, prof_scope, title="Open", stage="implementation"
    )
    await projects_service.update_project(
        db, prof_scope, project.id, status="active", open_to_join=True
    )
    periods = await service.ensure_periods(db, prof_scope, through=today + timedelta(days=10))
    await projects_service.join_project(db, student_a_scope, project.id)

    this_week = await service.ensure_obligations(db, prof_scope, periods[0].id)
    next_week = await service.ensure_obligations(db, prof_scope, periods[1].id)

    assert this_week == []
    assert [o.student_id for o in next_week] == [student_a.id]


async def test_the_professor_assigning_mid_week_still_owes_that_week(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The rule above is about joining, not about mid-week membership. A professor who assigns
    # someone on a Saturday knows what they are asking for, and that behaviour is unchanged.
    today = now().date()
    started = today - timedelta(days=3)
    await _calendar(db, prof_scope, effective_from=started, week_start_weekday=started.weekday())
    project = await projects_service.create_project(
        db, prof_scope, title="Assigned", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    periods = await service.ensure_periods(db, prof_scope, through=today + timedelta(days=10))

    assert [
        o.student_id for o in await service.ensure_obligations(db, prof_scope, periods[0].id)
    ] == [student_a.id]
