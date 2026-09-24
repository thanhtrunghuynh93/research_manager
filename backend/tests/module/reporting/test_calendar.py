"""REP-01/REP-06: the reporting calendar, generated periods, and per-membership obligations.

The deadline is fixed by rule — 23:59 local on the day before the weekly meeting — and the meeting
follows the period it discusses. With the proposed default (week Monday–Sunday, meeting Monday) a
period covering Mon 14 to Sun 20 September is discussed on Mon 21 and is due Sun 20 at 23:59.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ForbiddenError, NotFoundError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import models, repository, service

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


async def test_leaving_mid_week_takes_the_week_with_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A report covers a week, so a membership that did not last the week owes nothing for it.

    The earlier rule kept the week in progress, on the grounds that leaving should not be a way to
    drop a report already owed. This is the other reading: a project you are no longer on should
    not sit on your week at all.
    """
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    membership = await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    week = periods[0]
    derived = await service.ensure_obligations(db, prof_scope, week.id)
    assert [o.project_id for o in derived] == [project.id], "owed while they are on it"

    # Thursday of a Monday-to-Sunday week.
    await projects_service.end_membership(db, prof_scope, membership.id, left_on=date(2026, 9, 17))

    # The student's own screen.
    student_scope = await identity_service.scope_for(db, student_a)
    assert await service.list_obligations(db, student_scope, week.id) == []

    # And the professor's outstanding list, which must not say they owe a project they cannot open.
    outstanding = await service.unfulfilled_entries(db, week.id)
    assert [e.project_id for e in outstanding] == []


async def test_completing_a_project_takes_the_week_off_everyone_on_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A project the professor has called done owes no report, including the week in progress.

    Completing one already stopped obligations *deriving*; the ones derived before it stayed on
    the student's week and in the professor's outstanding list, so a student owed — and was
    emailed at 00:00 on the meeting day about — work that had just been called finished.
    """
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    periods = await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    week = periods[0]
    derived = await service.ensure_obligations(db, prof_scope, week.id)
    assert [o.project_id for o in derived] == [project.id], "owed while the project is active"

    await projects_service.update_project(db, prof_scope, project.id, status="completed")

    student_scope = await identity_service.scope_for(db, student_a)
    assert await service.list_obligations(db, student_scope, week.id) == [], "not the student's"
    outstanding = await service.unfulfilled_entries(db, week.id)
    assert [e.project_id for e in outstanding] == [], "and not the professor's outstanding list"

    # The row itself is kept: it is how the week was derived, and the history reads it (PROJ-02).
    assert await repository.list_obligations(db, prof_scope, week.id) != []


async def test_pausing_a_project_takes_the_week_off_too(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-06 names a paused project beside leave and holidays: none of them owe a week.
    await _calendar(db, prof_scope)
    project = await projects_service.create_project(
        db, prof_scope, title="On hold", stage="experimentation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    week = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, week.id)

    await projects_service.update_project(db, prof_scope, project.id, status="paused")

    student_scope = await identity_service.scope_for(db, student_a)
    assert await service.list_obligations(db, student_scope, week.id) == []


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


async def test_a_plan_written_in_the_older_shape_still_carries(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """`next_plan` is free-form JSON, and the report editor wrote a shape nothing read.

    It sent `{"outcomes": [text]}` where the baseline is frozen from `items[].planned_outcome`, so
    every plan a student typed into the app was dropped on its way to PROJ-04 and the assessment
    that followed reported that no baseline was in effect. The editor writes `items` now; rows in
    the old shape are already stored, and a plan written last week has to be readable this week.
    """
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
                "next_plan": {"outcomes": ["Fit the seasonal term"]},
            }
        ],
    )

    await service.ensure_obligations(db, prof_scope, periods[1].id)
    baselines = await service.freeze_baselines(db, prof_scope, periods[1].id)

    assert [item.planned_outcome for item in baselines[0].items] == ["Fit the seasonal term"]
    assert baselines[0].state.value == "frozen"


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


async def test_a_student_who_starts_a_project_owes_a_report_for_that_week(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_a_scope: Scope,
) -> None:
    """PROJ-07, and the point of the whole change: the chain closes without a professor in it.

    Starting a project owes the week it lands in. The student is not being handed work — they are
    announcing work already under way, and the report is how that week gets described.

    The calendar is anchored so the current period began three days ago whatever today's weekday
    is, rather than to a fixed date, because the rule under test is about landing part-way through
    a week and the test must not depend on which day it is run.
    """
    today = now().date()
    started = today - timedelta(days=3)
    await _calendar(db, prof_scope, effective_from=started, week_start_weekday=started.weekday())
    periods = await service.ensure_periods(db, prof_scope, through=today + timedelta(days=10))
    await projects_service.create_project(db, student_a_scope, title="Mine", stage="implementation")

    this_week = await service.ensure_obligations(db, prof_scope, periods[0].id)

    assert [o.student_id for o in this_week] == [student_a.id]


async def test_the_obligation_exists_before_the_nightly_job_runs(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_a_scope: Scope,
) -> None:
    """The half of "immediately" that the derivation rule alone does not give you.

    Deriving obligations is a nightly job. Without the event reporting subscribes to, a student who
    creates a project sees a project and no report until 00:15 the next morning, which reads as the
    system not having noticed. Nothing here calls `ensure_obligations`: creating the project is the
    only act, and the obligation has to exist afterwards.
    """
    today = now().date()
    started = today - timedelta(days=3)
    await _calendar(db, prof_scope, effective_from=started, week_start_weekday=started.weekday())
    period = (await service.ensure_periods(db, prof_scope, through=today + timedelta(days=10)))[0]

    await projects_service.create_project(db, student_a_scope, title="Mine", stage="implementation")

    owed = await service.list_obligations(db, prof_scope, period.id)
    assert [o.student_id for o in owed] == [student_a.id]


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

    assert this_week == [], "joining someone else's project is not the same as starting one"
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


# ---------------------------------------------------------------- one workspace at a time
#
# A professor's reads span every workspace they belong to (ADR 0016). The calendar panel is about
# one workspace, and reading the wide list made a brand-new workspace report the other one's open
# weeks in the same breath as saying it had no calendar at all.


async def test_periods_are_listed_for_the_workspace_being_worked_in(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _calendar(db, prof_scope)
    await service.ensure_periods(db, prof_scope, through=date(2026, 10, 12))
    home = prof_scope.workspace_id

    # Creating a workspace moves the professor there and keeps the one they were in.
    second = await identity_service.create_workspace(db, prof_scope, name="QA Lab")
    working = await identity_service.scope_for(db, prof)
    assert working.workspace_id == second.id
    assert working.workspace_ids == {second.id} and home not in working.workspace_ids, (
        "a member of the first, but not reading it"
    )

    assert await service.list_periods(db, working) == [], "the new workspace has no weeks yet"

    # ADR 0020: the widened read is bounded by `visible_to`, which is the workspace worked in, so
    # it no longer reaches the one just left.
    assert await service.list_periods(db, working, across_workspaces=True) == []


async def test_the_widened_list_is_ordered_by_workspace_as_well_as_by_week(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Two workspaces on the same calendar have a period each for the same Monday.

    `local_start` alone does not order that list, so which of the two came back first was
    postgres's choice — and a caller taking the newest eight got a different eight between loads.
    A session no longer spans (ADR 0020), so the Scope is widened by hand through the seam a
    spanning read would use.
    """
    await _calendar(db, prof_scope)
    await service.ensure_periods(db, prof_scope, through=date(2026, 10, 12))
    home = prof_scope.workspace_id

    second = await identity_service.create_workspace(db, prof_scope, name="QA Lab")
    spanning = await identity_service.scope_for(db, prof)
    await _calendar(db, spanning)
    await service.ensure_periods(db, spanning, through=date(2026, 10, 12))
    spanning = replace(spanning, workspace_ids=frozenset({home, second.id}))

    wide = await service.list_periods(db, spanning, across_workspaces=True)
    assert {period.workspace_id for period in wide} == {home, second.id}, "both workspaces"

    # Weeks still ascend, and the two rows sharing a Monday are always in the same order.
    keys = [(period.local_start, period.workspace_id) for period in wide]
    assert keys == sorted(keys), "a total order, not a week with two rows in postgres's order"

    # Asked again, the same answer — the property the eight-row lists on top of this depend on.
    again = await service.list_periods(db, spanning, across_workspaces=True)
    assert [period.id for period in again] == [period.id for period in wide]
