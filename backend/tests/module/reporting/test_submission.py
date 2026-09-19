"""REP-02/REP-03/REP-05: one weekly package, immutable versions, and per-entry change tracking.

AC-17 is the sharp edge: resubmitting after a revision request on one of two project entries must
leave the unchanged entry pointing at the version its content last changed in, so no new assessment
is created for work nobody touched.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import models, service

pytestmark = pytest.mark.module

TZ = "Asia/Ho_Chi_Minh"


class Week:
    """One configured period with a student enrolled on two active projects."""

    def __init__(
        self,
        period: object,
        projects: list[object],
        student_scope: Scope,
        memberships: list[object] | None = None,
    ) -> None:
        self.period = period
        self.projects = projects
        self.scope = student_scope
        self.memberships = memberships or []


async def _week(
    db: AsyncSession,
    prof_scope: Scope,
    student: identity_models.User,
    *,
    project_count: int = 2,
    grace_minutes: int = 0,
) -> Week:
    await service.configure_calendar(
        db,
        prof_scope,
        timezone=TZ,
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
        grace_minutes=grace_minutes,
    )
    projects = []
    memberships = []
    for index in range(project_count):
        project = await projects_service.create_project(
            db, prof_scope, title=f"Project {index}", stage="implementation"
        )
        await projects_service.update_project(db, prof_scope, project.id, status="active")
        memberships.append(
            await projects_service.add_member(
                db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
            )
        )
        projects.append(project)

    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, period.id)
    return Week(period, projects, await identity_service.scope_for(db, student), memberships)


def _entry(project_id: object, work: str = "Implemented the data loader") -> dict[str, object]:
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": work,
        "results": "The loader reproduces the published split sizes.",
        "deviations": "",
        "next_plan": {"items": [{"planned_outcome": "Run the baseline end to end"}]},
        "questions": "",
    }


async def test_one_package_carries_an_entry_for_every_required_project(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-02 / AC-01: one weekly package, one entry per project, separate assessments later.
    week = await _week(db, prof_scope, student_a)

    version = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id), _entry(week.projects[1].id)],
    )

    assert version.version_no == 1
    assert {e.project_id for e in version.entries} == {p.id for p in week.projects}


async def test_a_package_missing_a_required_project_is_refused(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-02: a package is complete only when each required project has an entry or an exemption.
    week = await _week(db, prof_scope, student_a)

    with pytest.raises(ValidationError):
        await service.submit_report(
            db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
        )


async def test_a_package_with_nothing_written_in_it_is_refused(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A week in which nothing was written is a mistake, not a week's work.

    The editor seeds itself from the autosaved draft, and a report submitted without one — the
    seed does this — used to reopen as empty boxes over a version that had content. Pressing
    Submit then wrote that emptiness over the record.
    """
    week = await _week(db, prof_scope, student_a)
    blank = [
        {"project_id": project.id, "stage": "implementation", "work_performed": "", "results": ""}
        for project in week.projects
    ]

    with pytest.raises(ValidationError):
        await service.submit_report(db, week.scope, period_id=week.period.id, entries=blank)


async def test_an_entry_with_every_box_empty_is_refused_by_name(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """An obligation is discharged per project, so emptiness is judged per project.

    This test used to assert the opposite — one non-empty field anywhere in the package was
    enough — on the reading that how much there is to say differs per project and judging that is
    the professor's. The reading holds, and is why the test here is emptiness and not adequacy.
    But at package level it let a wholly blank entry through whenever a sibling tab had text, and
    that project's obligation was then marked SUBMITTED: one press of one button could report
    every project a student is on, with nothing written for any of them.
    """
    week = await _week(db, prof_scope, student_a)

    with pytest.raises(ValidationError) as refused:
        await service.submit_report(
            db,
            week.scope,
            period_id=week.period.id,
            entries=[
                _entry(week.projects[0].id),
                {"project_id": week.projects[1].id, "stage": "theory", "work_performed": ""},
            ],
        )

    # Named, not merely refused: the student has to know which tab to go back to.
    assert str(week.projects[1].id) in refused.value.extra["empty_project_ids"]
    assert str(week.projects[0].id) not in refused.value.extra["empty_project_ids"]


async def test_an_entry_carrying_only_hours_still_counts_as_written(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The test is emptiness, not substance. A week that produced nothing but time spent is a
    # report a professor may want to read, and it is not this function's place to say otherwise.
    week = await _week(db, prof_scope, student_a)

    version = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[
            _entry(week.projects[0].id),
            {"project_id": week.projects[1].id, "stage": "theory", "hours": 3},
        ],
    )

    assert version.version_no == 1


async def test_an_obligation_says_whether_its_entry_was_submitted(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-08 on the obligation itself, so a screen can tell a finished week from a new one.

    `state` is `required` or `excused` and never changes on submission, so the screen that rendered
    it alone showed every project as outstanding however many times the week had been handed in.
    """
    week = await _week(db, prof_scope, student_a)

    before = await service.list_obligations(db, week.scope, week.period.id)
    assert {o.submitted for o in before} == {False}

    await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id), _entry(week.projects[1].id)],
    )

    after = await service.list_obligations(db, week.scope, week.period.id)
    assert {o.submitted for o in after} == {True}


async def test_an_excused_project_needs_no_entry(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a)
    obligations = await service.list_obligations(db, prof_scope, week.period.id)
    excused = next(o for o in obligations if o.project_id == week.projects[1].id)
    await service.excuse_obligation(db, prof_scope, excused.id, reason="Project paused for leave")

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    assert [e.project_id for e in version.entries] == [week.projects[0].id]


async def test_a_draft_is_autosaved_and_recovered(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-04: autosave and draft recovery.
    week = await _week(db, prof_scope, student_a)

    await service.save_draft(
        db, week.scope, period_id=week.period.id, content={"entries": [{"work": "half typed"}]}
    )
    report = await service.get_report(db, week.scope, period_id=week.period.id)

    assert report.draft_content == {"entries": [{"work": "half typed"}]}
    assert report.draft_saved_at is not None
    assert report.workflow_state is models.ReportState.DRAFT


async def test_submission_creates_an_immutable_version(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-05: submission creates an immutable version.
    week = await _week(db, prof_scope, student_a, project_count=1)
    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    with pytest.raises(Exception, match="immutable"):
        await db.execute(
            update(models.ReportVersion)
            .where(models.ReportVersion.id == version.id)
            .values(submitted_at=now())
        )
    await db.rollback()


async def test_a_retried_submission_does_not_create_a_second_version(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    entries = [_entry(week.projects[0].id)]

    first = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=entries, idempotency_key="abc123"
    )
    second = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=entries, idempotency_key="abc123"
    )

    assert first.id == second.id


async def test_the_original_submission_time_survives_later_versions(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-07 / AC-13: reminders and review status must not change the original submission time.
    week = await _week(db, prof_scope, student_a, project_count=1)
    await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )
    report = await service.get_report(db, week.scope, period_id=week.period.id)
    first_submitted_at = report.first_submitted_at

    await service.request_revision(
        db, prof_scope, report_id=report.id, project_id=week.projects[0].id, reason="Add the setup"
    )
    await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id, work="Implemented the loader and the setup")],
    )

    after = await service.get_report(db, week.scope, period_id=week.period.id)
    assert after.first_submitted_at == first_submitted_at


async def test_a_resubmission_keeps_the_unchanged_entry_pointing_at_its_old_version(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-17: only the changed entry produces a new draft assessment.
    week = await _week(db, prof_scope, student_a)
    first = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id), _entry(week.projects[1].id)],
    )
    report = await service.get_report(db, week.scope, period_id=week.period.id)
    await service.request_revision(
        db,
        prof_scope,
        report_id=report.id,
        project_id=week.projects[0].id,
        reason="Name the baseline you compared against",
    )

    second = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[
            _entry(week.projects[0].id, work="Implemented the loader; compared against CNN-B"),
            _entry(week.projects[1].id),
        ],
    )

    changed = next(e for e in second.entries if e.project_id == week.projects[0].id)
    unchanged = next(e for e in second.entries if e.project_id == week.projects[1].id)
    assert changed.content_changed_in_version_id == second.id
    assert unchanged.content_changed_in_version_id == first.id, "carried forward, not re-assessed"


async def test_leaving_a_project_does_not_make_the_week_unsubmittable(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The completeness check reads the obligations the student is actually shown.

    Leaving takes the project off the week (REP-01), so the editor stops offering a tab for it and
    the student cannot write an entry for it — and cannot rejoin, because that needs the professor.
    Read straight from the table, the check went on demanding an entry for the departed project and
    the week became permanently unsubmittable.
    """
    week = await _week(db, prof_scope, student_a)
    # Through the professor, only because a student may leave only as of today and this week is in
    # 2026. The state it produces is the one a student's own click produces.
    await projects_service.end_membership(
        db, prof_scope, week.memberships[0].id, left_on=date(2026, 9, 17)
    )

    still_owed = await service.list_obligations(db, week.scope, week.period.id)
    assert [o.project_id for o in still_owed] == [week.projects[1].id]

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[1].id)]
    )

    assert [e.project_id for e in version.entries] == [week.projects[1].id]


async def test_a_resubmission_keeps_the_entry_for_a_project_since_left(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """PROJ-02 and the copy on the leave button: what was submitted stays on the record.

    The new version becomes `current_version_id`, which is what the professor and the assessment
    pipeline read. Writing only the entries in the payload meant the first resubmission after a
    departure silently deleted a week's submitted work from the record it is read through.
    """
    week = await _week(db, prof_scope, student_a)
    first = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[
            _entry(week.projects[0].id, work="Ran the ablation over the 2019 split"),
            _entry(week.projects[1].id),
        ],
    )
    await projects_service.end_membership(
        db, prof_scope, week.memberships[0].id, left_on=date(2026, 9, 17)
    )

    second = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[1].id, work="Wrote the method section")],
    )

    carried = next(e for e in second.entries if e.project_id == week.projects[0].id)
    assert carried.work_performed == "Ran the ablation over the 2019 split"
    # Nothing about it changed, so AC-17 keeps it pointing at the version it was written in and no
    # second assessment falls due for a project nobody reported on this week.
    assert carried.content_changed_in_version_id == first.id


async def test_the_version_number_counts_from_the_history_not_from_the_current_version(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-05: a resubmission adds to the history, so the sequence belongs to the history.

    `current_version_id` and the highest version are normally the same, and when they are not — a
    current version pointed back at an earlier one by a restore or a correction — counting from the
    current one reissues a number the table already holds. The unique constraint refuses the
    insert, and the week becomes unsubmittable with nothing on screen but "that record already
    exists". Reproduced on the live deployment, whose report had versions 1, 2 and 3 with 1 current.
    """
    week = await _week(db, prof_scope, student_a, project_count=1)
    first = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )
    second = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id, work="Second pass over the loader")],
    )
    assert (first.version_no, second.version_no) == (1, 2)

    # Roll the report back to its first version, as a restore or a hand-applied correction would.
    report = await service.get_report(db, week.scope, period_id=week.period.id)
    await db.execute(
        update(models.WeeklyReport)
        .where(models.WeeklyReport.id == report.id)
        .values(current_version_id=first.id)
    )

    third = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id, work="Third pass, after the rollback")],
    )

    assert third.version_no == 3, "one past the highest, not one past the current"


async def test_reported_hours_do_not_count_as_a_content_change(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Hours are optional self-reported context, never evidence of productivity (REP-03).
    week = await _week(db, prof_scope, student_a, project_count=1)
    first = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    second = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[{**_entry(week.projects[0].id), "hours": 12}],
    )

    entry = second.entries[0]
    assert entry.content_changed_in_version_id == first.id


async def test_a_late_submission_keeps_its_real_timestamp_and_is_marked_late(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-06: late reports retain their actual timestamps.
    week = await _week(db, prof_scope, student_a, project_count=1)
    moved_deadline = await _move_deadline_into_the_past(db, week)
    started = now()

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    assert version.timing_status is models.TimingStatus.LATE
    assert version.submitted_at >= started, "the real submission time is kept, not the deadline"
    assert version.submitted_at > moved_deadline


async def test_an_extension_makes_a_later_submission_on_time(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    await _move_deadline_into_the_past(db, week)
    obligations = await service.list_obligations(db, prof_scope, week.period.id)
    await service.extend_obligation(
        db, prof_scope, obligations[0].id, until=now() + timedelta(days=2), reason="Cluster outage"
    )

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    assert version.timing_status is models.TimingStatus.ON_TIME


async def _move_deadline_into_the_past(db: AsyncSession, week: Week) -> datetime:
    """The period was generated for a future week; pull its deadline behind us."""
    deadline = now() - timedelta(hours=1)
    await db.execute(
        update(models.ReportingPeriod)
        .where(models.ReportingPeriod.id == week.period.id)
        .values(deadline_utc=deadline)
    )
    return deadline


async def test_a_student_cannot_submit_for_someone_else(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    other = await identity_service.scope_for(db, student_b)

    with pytest.raises(ValidationError):
        await service.submit_report(
            db, other, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
        )


async def test_a_student_cannot_read_another_students_report(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # AC-02: access is denied in the API, search, downloads, and exports alike.
    week = await _week(db, prof_scope, student_a, project_count=1)
    await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )
    other = await identity_service.scope_for(db, student_b)

    with pytest.raises(NotFoundError):
        await service.get_report(db, other, period_id=week.period.id, student_id=student_a.id)


async def test_the_professor_reads_every_report_in_the_workspace(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    report = await service.get_report(
        db, prof_scope, period_id=week.period.id, student_id=student_a.id
    )

    assert report.student_id == student_a.id
    assert report.workflow_state is models.ReportState.SUBMITTED


async def test_a_revision_request_targets_one_project_entry(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a)
    await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id), _entry(week.projects[1].id)],
    )
    report = await service.get_report(db, week.scope, period_id=week.period.id)

    await service.request_revision(
        db,
        prof_scope,
        report_id=report.id,
        project_id=week.projects[0].id,
        reason="Name the baseline",
    )

    after = await service.get_report(db, week.scope, period_id=week.period.id)
    requests = await service.list_revision_requests(db, week.scope, report_id=report.id)
    assert after.workflow_state is models.ReportState.REVISION_REQUESTED
    assert [r.project_id for r in requests] == [week.projects[0].id]


async def test_only_the_professor_requests_a_revision(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )
    report = await service.get_report(db, week.scope, period_id=week.period.id)

    with pytest.raises(ForbiddenError):
        await service.request_revision(
            db, week.scope, report_id=report.id, project_id=week.projects[0].id, reason="no"
        )


async def test_an_entry_for_a_project_the_student_is_not_on_is_refused(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1)
    foreign = await projects_service.create_project(
        db, prof_scope, title="Not theirs", stage="theory"
    )

    with pytest.raises(ValidationError):
        await service.submit_report(
            db,
            week.scope,
            period_id=week.period.id,
            entries=[_entry(week.projects[0].id), _entry(foreign.id)],
        )


async def test_two_reports_for_one_student_and_period_cannot_exist(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The uq_report invariant from requirements section 9, enforced by the database.
    week = await _week(db, prof_scope, student_a, project_count=1)
    await service.save_draft(db, week.scope, period_id=week.period.id, content={})

    db.add(
        models.WeeklyReport(
            workspace_id=week.scope.workspace_id,
            student_id=student_a.id,
            period_id=week.period.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_a_submission_inside_the_configured_grace_is_on_time(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-01: `grace_minutes` is configurable, stored, and returned by the API.

    It was also never read: `_timing_status` passed a hardcoded zero to the one production call
    site of `effective_deadline`, so a professor who set thirty minutes of grace granted none.
    """
    week = await _week(db, prof_scope, student_a, project_count=1, grace_minutes=30)
    # Eleven minutes past the deadline, and well inside the half hour the professor allowed.
    await db.execute(
        update(models.ReportingPeriod)
        .where(models.ReportingPeriod.id == week.period.id)
        .values(deadline_utc=now() - timedelta(minutes=11))
    )

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    assert version.timing_status is models.TimingStatus.ON_TIME


async def test_a_submission_past_the_grace_is_still_late(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, student_a, project_count=1, grace_minutes=30)
    await db.execute(
        update(models.ReportingPeriod)
        .where(models.ReportingPeriod.id == week.period.id)
        .values(deadline_utc=now() - timedelta(minutes=45))
    )

    version = await service.submit_report(
        db, week.scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    assert version.timing_status is models.TimingStatus.LATE


async def test_the_missed_deadline_reminder_waits_for_the_grace_to_close(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """Otherwise the email saying they missed it arrives while they are still inside it."""
    await service.configure_calendar(
        db,
        prof_scope,
        timezone=TZ,
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
        grace_minutes=30,
    )

    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]

    assert period.reminder_due_utc > period.deadline_utc + timedelta(minutes=30)


# ------------------------------------------------- the submission survives a provider outage


async def test_a_dead_embedding_provider_does_not_lose_the_submission(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-13: the submitted version is the thing that cannot be lost.

    Indexing the entries runs inside the submitting transaction so the chunks commit with the
    version that cites them, and that puts one call to the embedding provider on the student's
    critical path. `events.emit` runs handlers with no isolation, so a provider that is down, rate
    limited or out of credit used to surface as a 500 — at 23:59, for every student at once.
    """
    from app.evidence import service as evidence_service

    week = await _week(db, prof_scope, student_a, project_count=1)

    async def _provider_is_down(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("429 insufficient_quota: you have no credits remaining")

    monkeypatch.setattr(evidence_service, "embed_texts", _provider_is_down)

    version = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id)],
    )

    assert version.version_no == 1, "the week is recorded even though nothing could be indexed"
    stored = await service.get_report(db, week.scope, period_id=week.period.id)
    assert stored.workflow_state is models.ReportState.SUBMITTED


async def test_the_failed_indexing_is_queued_rather_than_dropped(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recoverable, not forgotten: the retry job is recorded against the committing transaction."""
    from app.core.jobs import PENDING_DEFERS
    from app.evidence import service as evidence_service

    week = await _week(db, prof_scope, student_a, project_count=1)

    async def _provider_is_down(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(evidence_service, "embed_texts", _provider_is_down)
    before = len(db.info.get(PENDING_DEFERS, []))

    await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id)],
    )

    # One for the assessment pipeline, one for the re-index: the second is what this fix adds.
    assert len(db.info.get(PENDING_DEFERS, [])) > before + 1


async def test_the_entries_are_indexed_when_the_provider_comes_back(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the trade: recoverable means actually recovered, not merely survived."""
    from app.evidence import service as evidence_service

    week = await _week(db, prof_scope, student_a, project_count=1)

    async def _provider_is_down(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(evidence_service, "embed_texts", _provider_is_down)
    version = await service.submit_report(
        db,
        week.scope,
        period_id=week.period.id,
        entries=[_entry(week.projects[0].id)],
    )
    monkeypatch.undo()

    # What the retry job does, against the same version id it was queued with.
    indexed = await evidence_service.index_report_entries(db, version.id)

    assert indexed == 1
    hits = await evidence_service.search_evidence(
        db, week.scope, query="loader reproduces the published split"
    )
    assert hits, "the week is citable once the provider answers again"
