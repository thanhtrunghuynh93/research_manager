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

    def __init__(self, period: object, projects: list[object], student_scope: Scope) -> None:
        self.period = period
        self.projects = projects
        self.scope = student_scope


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
    for index in range(project_count):
        project = await projects_service.create_project(
            db, prof_scope, title=f"Project {index}", stage="implementation"
        )
        await projects_service.update_project(db, prof_scope, project.id, status="active")
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
        )
        projects.append(project)

    period = (await service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await service.ensure_obligations(db, prof_scope, period.id)
    return Week(period, projects, await identity_service.scope_for(db, student))


def _entry(project_id: object, work: str = "Implemented the data loader") -> dict[str, object]:
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": work,
        "results": "The loader reproduces the published split sizes.",
        "deviations": "",
        "next_plan": {"outcomes": ["Run the baseline end to end"]},
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
