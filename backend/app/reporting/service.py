"""Reporting use cases: calendar, obligations, drafts, and the submission lifecycle.

Requirements REP-01..06. Submission persists the work first and never blocks on anything external
(requirements §10): the version and its entries are written in one transaction, and jobs that read
them run afterwards.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import NotFoundError, ValidationError
from app.core.types import Role
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.projects.schemas import PlanBaselineOut
from app.reporting import (  # noqa: F401  (policies register)
    artifacts,
    calendar,
    events,
    policies,
    repository,
)
from app.reporting.models import (
    CalendarConfig,
    ObligationState,
    ProjectReportEntry,
    ReportingObligation,
    ReportingPeriod,
    ReportState,
    ReportVersion,
    RevisionRequest,
    TimingStatus,
    WeeklyReport,
)
from app.reporting.schemas import (
    CalendarConfigOut,
    EntryOut,
    ObligationOut,
    PeriodOut,
    ReportOut,
    RevisionRequestOut,
    VersionOut,
    VersionSummaryOut,
)

log = logging.getLogger(__name__)
# Eight weeks ahead, as the architecture's periodic task does (architecture §7.1).
# How far back the daily baseline task will still catch up, if the worker was down.
BASELINE_CATCHUP = timedelta(days=14)
DEFAULT_HORIZON = timedelta(weeks=8)

# Fields whose change means the research content changed. `hours` is excluded on purpose: it is
# optional, self-reported, and must not trigger a new assessment (REP-03, ASSESS-09).
CONTENT_FIELDS = (
    "stage",
    "milestone_ids",
    "planned_work_ref",
    "work_performed",
    "results",
    "experiments",
    "deviations",
    "next_plan",
    "questions",
    "evidence_refs",
)


# ------------------------------------------------------------------ calendar (REP-01)


async def current_calendar(session: AsyncSession, scope: Scope) -> CalendarConfigOut | None:
    """The calendar version in force, or absent when none has been configured (REP-01).

    Absent is a state a screen has to be able to tell from "configured": without it the only
    signal is an empty period list, which lies the moment a calendar is replaced after periods
    already exist.
    """
    row = await repository.latest_calendar(session, scope.workspace_id)
    return CalendarConfigOut.model_validate(row) if row is not None else None


async def configure_calendar(
    session: AsyncSession,
    scope: Scope,
    *,
    timezone: str,
    meeting_weekday: int,
    week_start_weekday: int,
    effective_from: date,
    grace_minutes: int = 0,
) -> CalendarConfigOut:
    """A new version applies to future periods; periods already materialised keep their deadline."""
    scope.require_prof()
    previous = await repository.latest_calendar(session, scope.workspace_id)
    config = CalendarConfig(
        workspace_id=scope.workspace_id,
        version=1 if previous is None else previous.version + 1,
        timezone=timezone,
        meeting_weekday=meeting_weekday,
        week_start_weekday=week_start_weekday,
        grace_minutes=grace_minutes,
        effective_from=effective_from,
        created_by=scope.user_id,
    )
    session.add(config)
    await session.flush()
    write_audit(
        session,
        scope=scope,
        action="calendar.configured",
        target_table="calendar_configs",
        target_id=config.id,
        after={"version": config.version, "meeting_weekday": meeting_weekday},
    )
    return CalendarConfigOut.model_validate(config)


async def ensure_periods(
    session: AsyncSession, scope: Scope, *, through: date | None = None
) -> list[PeriodOut]:
    """Materialise periods up to `through`, skipping any that already exist (REP-01)."""
    scope.require_prof()
    horizon = through or (now().date() + DEFAULT_HORIZON)
    latest = await repository.latest_calendar(session, scope.workspace_id)
    if latest is None:
        raise NotFoundError("no reporting calendar is configured for this workspace")

    last = await repository.last_period(session, scope.workspace_id)
    if last is None:
        first_config = (
            await repository.calendar_for(session, scope.workspace_id, latest.effective_from)
        ) or latest
        cursor = calendar.first_period_start(
            first_config.effective_from, first_config.week_start_weekday
        )
    else:
        cursor = calendar.next_period_start(last.local_end, latest.week_start_weekday)

    created = False
    while cursor <= horizon:
        config = await repository.calendar_for(session, scope.workspace_id, cursor) or latest
        dates = calendar.period_dates(
            cursor,
            meeting_weekday=config.meeting_weekday,
            timezone=config.timezone,
            grace_minutes=config.grace_minutes,
        )
        session.add(
            ReportingPeriod(
                workspace_id=scope.workspace_id,
                calendar_config_id=config.id,
                local_start=dates.local_start,
                local_end=dates.local_end,
                start_utc=dates.start_utc,
                end_utc=dates.end_utc,
                meeting_date=dates.meeting_date,
                deadline_utc=dates.deadline_utc,
                reminder_due_utc=dates.reminder_due_utc,
            )
        )
        created = True
        cursor = calendar.next_period_start(dates.local_end, config.week_start_weekday)

    if created:
        await session.flush()
    rows = await repository.list_periods(session, scope, through=horizon)
    return [PeriodOut.model_validate(row) for row in rows]


async def get_period(session: AsyncSession, scope: Scope, period_id: UUID) -> PeriodOut:
    """One period, or NotFound when it is outside the caller's workspace."""
    return PeriodOut.model_validate(await _require_period(session, scope, period_id))


async def list_periods(
    session: AsyncSession, scope: Scope, *, through: date | None = None
) -> list[PeriodOut]:
    rows = await repository.list_periods(session, scope, through=through)
    return [PeriodOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ obligations (REP-01, REP-06)


async def ensure_obligations(
    session: AsyncSession, scope: Scope, period_id: UUID
) -> list[ObligationOut]:
    """Derive who owes a report for this period from memberships, project status, and bounds."""
    scope.require_prof()
    period = await _require_period(session, scope, period_id)

    created = False
    for membership in await projects_service.reporting_memberships(
        session, scope, local_start=period.local_start, local_end=period.local_end
    ):
        existing = await repository.obligation_for_membership(session, membership.id, period.id)
        if existing is not None:
            continue
        session.add(
            ReportingObligation(
                workspace_id=scope.workspace_id,
                membership_id=membership.id,
                period_id=period.id,
                student_id=membership.student_id,
                project_id=membership.project_id,
                state=ObligationState.REQUIRED,
            )
        )
        created = True
    if created:
        await session.flush()
    return await list_obligations(session, scope, period_id)


async def list_obligations(
    session: AsyncSession, scope: Scope, period_id: UUID, *, student_id: UUID | None = None
) -> list[ObligationOut]:
    """Each obligation the caller still owes, and whether the current version answers it.

    Obligations for a project the student has since left are left out. The row stays — it is how
    the week was derived and the professor's history reads it — but a project you are no longer on
    should not sit on your week, and `_obligations_still_owed` is where that is decided for both
    of the screens that ask.

    `submitted` is read from the same place `unfulfilled_entries` reads it — the entries on the
    report's current version — so the student's screen and the professor's outstanding list cannot
    disagree about whether a week is done. One query per student, not per obligation.
    """
    period = await _require_period(session, scope, period_id)
    rows = await _obligations_still_owed(session, period, scope=scope, student_id=student_id)
    submitted_by_student: dict[UUID, set[UUID]] = {}
    out = []
    for row in rows:
        if row.student_id not in submitted_by_student:
            submitted_by_student[row.student_id] = await repository.submitted_project_ids(
                session, period_id=period_id, student_id=row.student_id
            )
        out.append(
            ObligationOut.model_validate(row).model_copy(
                update={"submitted": row.project_id in submitted_by_student[row.student_id]}
            )
        )
    return out


async def _obligations_still_owed(
    session: AsyncSession,
    period: ReportingPeriod,
    *,
    scope: Scope,
    student_id: UUID | None = None,
) -> list[ReportingObligation]:
    """The period's obligations, minus those whose membership did not last the week (REP-01).

    A report covers a week, so a membership that ended inside it owes nothing for it — the rule
    `memberships_active_in_range` derives by, applied again on the way out because an obligation
    derived before someone left is still sitting in the table.
    """
    rows = await repository.list_obligations(session, scope, period.id, student_id=student_id)
    still_owed = await projects_service.memberships_still_owing(
        session, [row.membership_id for row in rows], through=period.local_end
    )
    return [row for row in rows if row.membership_id in still_owed]


async def excuse_obligation(
    session: AsyncSession, scope: Scope, obligation_id: UUID, *, reason: str
) -> ObligationOut:
    """REP-06: leave, holidays, and paused projects are recorded, not treated as missing reports."""
    scope.require_prof()
    obligation = await _require_obligation(session, scope, obligation_id)
    obligation.state = ObligationState.EXCUSED
    obligation.excuse_reason = reason
    _audit(session, scope, "obligation.excused", obligation.id, after={"reason": reason})
    await session.flush()
    return ObligationOut.model_validate(obligation)


async def extend_obligation(
    session: AsyncSession, scope: Scope, obligation_id: UUID, *, until: datetime, reason: str
) -> ObligationOut:
    """An extension moves the effective deadline for one obligation; it is not an exemption."""
    scope.require_prof()
    obligation = await _require_obligation(session, scope, obligation_id)
    obligation.extension_until_utc = until
    obligation.extension_reason = reason
    _audit(
        session,
        scope,
        "obligation.extended",
        obligation.id,
        after={"until": until.isoformat(), "reason": reason},
    )
    await session.flush()
    return ObligationOut.model_validate(obligation)


async def freeze_baselines(
    session: AsyncSession, scope: Scope, period_id: UUID
) -> list[PlanBaselineOut]:
    """PROJ-04: at the start of a period, fix the plan each membership will be assessed against.

    The plan comes from the next-week plan in the previous period's report entry. When there is
    none — a new member, a missing or late report, a paused project — the baseline is recorded as
    empty and the student enters a first plan in the current report (AC-18).
    """
    scope.require_prof()
    period = await _require_period(session, scope, period_id)
    previous = await repository.period_before(session, scope.workspace_id, period.local_start)

    frozen: list[PlanBaselineOut] = []
    for obligation in await repository.list_obligations(session, scope, period_id):
        existing = await projects_service.latest_baseline(
            session, scope, membership_id=obligation.membership_id, period_id=period_id
        )
        if existing is not None:
            frozen.append(existing)
            continue

        items, source_entry_id = await _carried_plan(
            session, scope, previous, obligation.student_id, obligation.project_id
        )
        frozen.append(
            await projects_service.freeze_baseline(
                session,
                scope,
                membership_id=obligation.membership_id,
                period_id=period_id,
                items=items,
                source_entry_id=source_entry_id,
            )
        )
    return frozen


async def _carried_plan(
    session: AsyncSession,
    scope: Scope,
    previous: ReportingPeriod | None,
    student_id: UUID,
    project_id: UUID,
) -> tuple[list[dict[str, Any]], UUID | None]:
    """The `next_plan` items from last week's entry for this project, if there is one."""
    if previous is None:
        return [], None
    report = await repository.get_report(
        session, scope, period_id=previous.id, student_id=student_id
    )
    if report is None or report.current_version_id is None:
        return [], None

    entries = await repository.entries_of_version(session, report.current_version_id)
    entry = entries.get(project_id)
    if entry is None:
        return [], None

    return _plan_items(entry.next_plan), entry.id


def _plan_items(next_plan: Any) -> list[dict[str, Any]]:
    """The commitments in a next-week plan, in the one shape a baseline is frozen from.

    `next_plan` is free-form JSON (REP-03 leaves its structure to the client) and two shapes
    reached the column. `{"items": [{"planned_outcome": …, "weight": …}]}` is the one a baseline
    needs, because PROJ-04 weights the commitments; `{"outcomes": ["…"]}` is what the report editor
    wrote, and nothing read it — so every plan a student typed was dropped on its way to becoming
    next week's baseline, and the assessment that followed said "no plan baseline was in effect".

    The editor now writes `items`. The other shape is still accepted because rows carrying it are
    already stored, and a plan written last week has to be readable this week.
    """
    if not isinstance(next_plan, dict):
        return []
    items = next_plan.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict) and item.get("planned_outcome")]
    outcomes = next_plan.get("outcomes")
    if isinstance(outcomes, list):
        return [{"planned_outcome": str(outcome)} for outcome in outcomes if str(outcome).strip()]
    return []


# ------------------------------------------------------------------ drafts and submission


async def get_report(
    session: AsyncSession, scope: Scope, *, period_id: UUID, student_id: UUID | None = None
) -> ReportOut:
    subject = student_id or scope.user_id
    report = await repository.get_report(session, scope, period_id=period_id, student_id=subject)
    if report is None:
        raise NotFoundError("report not found")
    return ReportOut.model_validate(report)


async def save_draft(
    session: AsyncSession, scope: Scope, *, period_id: UUID, content: dict[str, Any]
) -> ReportOut:
    """REP-04: autosave. The draft is overwritten in place; submitted versions are untouched."""
    report = await _open_report(session, scope, period_id)
    report.draft_content = content
    report.draft_saved_at = now()
    await session.flush()
    return ReportOut.model_validate(report)


async def submit_report(
    session: AsyncSession,
    scope: Scope,
    *,
    period_id: UUID,
    entries: list[dict[str, Any]],
    idempotency_key: str | None = None,
) -> VersionOut:
    """REP-05: create an immutable version; a resubmission adds one and never replaces history."""
    report = await _open_report(session, scope, period_id)
    if idempotency_key:
        existing = await repository.version_by_idempotency_key(session, report.id, idempotency_key)
        if existing is not None:
            return await _version_out(session, scope, existing)

    period = await _require_period(session, scope, period_id)
    # The same set the editor builds its tabs from, and for the same reason: an obligation whose
    # membership ended inside the week is not owed (REP-01). Read raw, the completeness check
    # demanded an entry for a project the student had left — which they cannot write and cannot
    # rejoin — so one departure made the week permanently unsubmittable.
    obligations = await _obligations_still_owed(
        session, period, scope=scope, student_id=report.student_id
    )
    submitted = {UUID(str(entry["project_id"])) for entry in entries}
    _check_package_is_complete(obligations, submitted)
    # Titles resolved only when the check is about to fail, so the ordinary submission pays
    # nothing for a message it will never see.
    _check_package_says_something(
        entries,
        titles=(
            {}
            if all(_entry_says_something(entry) for entry in entries)
            else {
                project_id: await projects_service.project_title(session, project_id)
                for project_id in submitted
            }
        ),
    )

    at = now()
    previous_version_id = report.current_version_id
    previous_entries = (
        await repository.entries_of_version(session, previous_version_id)
        if previous_version_id is not None
        else {}
    )

    version = ReportVersion(
        workspace_id=scope.workspace_id,
        report_id=report.id,
        version_no=await _next_version_no(session, report),
        author_id=scope.user_id,
        submitted_at=at,
        idempotency_key=idempotency_key,
        timing_status=_timing_status(
            period, obligations, at, grace_minutes=await grace_minutes_for(session, period)
        ),
    )
    session.add(version)
    await session.flush()

    for payload in entries:
        content_hash = _content_hash(payload)
        previous = previous_entries.get(UUID(str(payload["project_id"])))
        unchanged = previous is not None and previous.content_hash == content_hash
        session.add(
            ProjectReportEntry(
                workspace_id=scope.workspace_id,
                report_version_id=version.id,
                project_id=UUID(str(payload["project_id"])),
                stage=str(payload.get("stage", "")),
                milestone_ids=payload.get("milestone_ids") or [],
                planned_work_ref=payload.get("planned_work_ref") or {},
                work_performed=str(payload.get("work_performed", "")),
                results=str(payload.get("results", "")),
                experiments=payload.get("experiments") or [],
                deviations=str(payload.get("deviations", "")),
                next_plan=payload.get("next_plan") or {},
                questions=str(payload.get("questions", "")),
                evidence_refs=payload.get("evidence_refs") or [],
                hours=payload.get("hours"),
                content_hash=content_hash,
                # AC-17: an entry nobody touched keeps pointing at the version it last changed in.
                content_changed_in_version_id=(
                    previous.content_changed_in_version_id if unchanged and previous else version.id
                ),
            )
        )

    # An entry the package no longer covers is carried across rather than dropped. The only way to
    # be in this branch is a project that stopped being owed after it was written — one the student
    # left, or one excused since — and the new version becomes `current_version_id`, which is what
    # the professor and the assessment pipeline read. Leaving it out would let a resubmission
    # delete submitted work from the record, against what ending a membership promises: "what you
    # have already submitted stays on the record".
    for project_id, entry in previous_entries.items():
        if project_id not in submitted:
            session.add(_carried_entry(entry, version.id))

    report.current_version_id = version.id
    report.workflow_state = (
        ReportState.SUBMITTED if previous_version_id is None else ReportState.RESUBMITTED
    )
    if report.first_submitted_at is None:
        report.first_submitted_at = at  # written once; never moved by a later version (AC-13)
    await _resolve_open_revision_requests(session, report.id, version.id)

    _audit(
        session,
        scope,
        "report.submitted",
        version.id,
        table="report_versions",
        after={"version_no": version.version_no, "timing": version.timing_status.value},
    )
    await session.flush()

    # Read the week's attachments now that the week is finished (REP-04). Queued before the event
    # so the reading jobs are enqueued ahead of the assessment the event triggers — with one worker
    # that means the text is indexed before the snapshot is taken. It is an ordering by insertion
    # rather than a guarantee: under a pool the assessment can still start first, and a snapshot
    # missing an attachment is what the pipeline's confidence and the professor's re-run are for.
    queued = await artifacts.read_attachments_for(
        session, student_id=report.student_id, period_id=period_id
    )
    if queued:
        log.info("queued %d attachment(s) to be read for the submitted week", queued)

    await events.emit(
        events.ReportSubmitted(
            workspace_id=scope.workspace_id,
            report_id=report.id,
            report_version_id=version.id,
            student_id=report.student_id,
            period_id=period_id,
            resubmitted=previous_version_id is not None,
        ),
        session,
    )
    return await _version_out(session, scope, version)


async def request_revision(
    session: AsyncSession,
    scope: Scope,
    *,
    report_id: UUID,
    reason: str,
    project_id: UUID | None = None,
) -> RevisionRequestOut:
    """REP-05: the request targets a specific project entry.

    The report returns to the student in state `revision_requested`; the submitted version and its
    entries stay exactly as they were.
    """
    scope.require_prof()
    report = await repository.get_report_by_id(session, scope, report_id)
    if report is None:
        raise NotFoundError("report not found")
    if report.current_version_id is None:
        raise ValidationError("nothing has been submitted to revise")

    request = RevisionRequest(
        workspace_id=scope.workspace_id,
        report_id=report.id,
        report_version_id=report.current_version_id,
        project_id=project_id,
        reason=reason,
        requested_by=scope.user_id,
    )
    session.add(request)
    report.workflow_state = ReportState.REVISION_REQUESTED
    _audit(
        session,
        scope,
        "report.revision_requested",
        report.id,
        table="weekly_reports",
        after={"project_id": str(project_id) if project_id else None, "reason": reason},
    )
    await session.flush()
    await events.emit(
        events.RevisionRequested(
            workspace_id=scope.workspace_id,
            report_id=report.id,
            request_id=request.id,
            period_id=report.period_id,
            student_id=report.student_id,
            project_id=project_id,
            reason=reason,
        ),
        session,
    )
    return RevisionRequestOut.model_validate(request)


async def list_revision_requests(
    session: AsyncSession, scope: Scope, *, report_id: UUID
) -> list[RevisionRequestOut]:
    rows = await repository.list_revision_requests(session, scope, report_id)
    return [RevisionRequestOut.model_validate(row) for row in rows]


async def mark_reviewed(session: AsyncSession, scope: Scope, *, report_id: UUID) -> ReportOut:
    scope.require_prof()
    report = await repository.get_report_by_id(session, scope, report_id)
    if report is None:
        raise NotFoundError("report not found")
    report.workflow_state = ReportState.REVIEWED
    _audit(session, scope, "report.reviewed", report.id, table="weekly_reports")
    await session.flush()
    return ReportOut.model_validate(report)


async def get_version(session: AsyncSession, scope: Scope, version_id: UUID) -> VersionOut:
    version = await repository.get_version(session, scope, version_id)
    if version is None:
        raise NotFoundError("report version not found")
    return await _version_out(session, scope, version)


async def list_versions(
    session: AsyncSession, scope: Scope, *, report_id: UUID
) -> list[VersionSummaryOut]:
    """Every version of one report, for the screen that reads a week back (REP-05).

    The report is fetched first so that a report belonging to another workspace is a 404 rather
    than an empty list: an empty list is a real state — a report drafted and never submitted — and
    the two must not look the same.
    """
    report = await repository.get_report_by_id(session, scope, report_id)
    if report is None:
        raise NotFoundError("report not found")
    rows = await repository.list_versions(session, scope, report_id)
    return [VersionSummaryOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ job-level reads (REP-08)
#
# The worker has no Scope: it acts for the system, not for a person. These functions are the only
# unscoped entry points, and each one returns facts about obligations rather than report content.


@dataclass(frozen=True, slots=True)
class UnfulfilledEntry:
    student_id: UUID
    project_id: UUID
    project_title: str


async def period_for_job(session: AsyncSession, period_id: UUID) -> PeriodOut | None:
    row = await repository.period_row(session, period_id)
    return None if row is None else PeriodOut.model_validate(row)


@dataclass(frozen=True, slots=True)
class VersionOwner:
    """Who a submitted version belongs to, and where. A job-level read: no Scope to hand."""

    workspace_id: UUID
    student_id: UUID


async def version_owner_for_job(
    session: AsyncSession, report_version_id: UUID
) -> VersionOwner | None:
    """The workspace and student behind one submitted version, or absent.

    The evidence re-index job carries only the version id — the event it stands in for is long
    gone by then — so it reads the owner back rather than trusting arguments that could have been
    serialised under a different account.
    """
    version = await session.get(ReportVersion, report_version_id)
    if version is None:
        return None
    report = await session.get(WeeklyReport, version.report_id)
    if report is None:
        return None
    return VersionOwner(workspace_id=report.workspace_id, student_id=report.student_id)


async def period_timezone(session: AsyncSession, period_id: UUID) -> str:
    """The timezone the period's deadline was expressed in, for rendering it back (REP-01)."""
    row = await repository.period_row(session, period_id)
    if row is None:
        raise NotFoundError("reporting period not found")
    config = await session.get(CalendarConfig, row.calendar_config_id)
    return "UTC" if config is None else config.timezone


async def periods_awaiting_reminder(
    session: AsyncSession, *, at: datetime | None = None
) -> list[PeriodOut]:
    rows = await repository.periods_awaiting_reminder(session, instant=at or now())
    return [PeriodOut.model_validate(row) for row in rows]


async def periods_with_deadline_between(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    workspace_id: UUID | None = None,
) -> list[PeriodOut]:
    rows = await repository.periods_with_deadline_between(
        session, start=start, end=end, workspace_id=workspace_id
    )
    return [PeriodOut.model_validate(row) for row in rows]


async def unfulfilled_entries(
    session: AsyncSession, period_id: UUID, *, at: datetime | None = None
) -> list[UnfulfilledEntry]:
    """REP-08: an obligation is unfulfilled when no package has been submitted or a required
    project entry is missing, with no recorded exemption and no extension still running.

    Evaluated at `at`, which the caller sets to the moment it is about to act, so a submission at
    23:59 is seen (AC-19).
    """
    instant = at or now()
    unfulfilled: list[UnfulfilledEntry] = []
    submitted_by_student: dict[UUID, set[UUID]] = {}

    period = await repository.get_period_unscoped(session, period_id)
    required = await repository.required_obligations_at(session, period_id, instant=instant)
    # The same rule the student's own screen applies, from the same place: without it a professor
    # is told a student owes a report for a project that student can no longer even open.
    if period is not None:
        still_owed = await projects_service.memberships_still_owing(
            session, [o.membership_id for o in required], through=period.local_end
        )
        required = [o for o in required if o.membership_id in still_owed]

    for obligation in required:
        if obligation.student_id not in submitted_by_student:
            submitted_by_student[obligation.student_id] = await repository.submitted_project_ids(
                session, period_id=period_id, student_id=obligation.student_id
            )
        if obligation.project_id in submitted_by_student[obligation.student_id]:
            continue
        unfulfilled.append(
            UnfulfilledEntry(
                student_id=obligation.student_id,
                project_id=obligation.project_id,
                project_title=await projects_service.project_title(session, obligation.project_id),
            )
        )
    return unfulfilled


@dataclass(frozen=True, slots=True)
class EntryForAssessment:
    id: UUID
    project_id: UUID
    stage: str
    text: str
    changed_in_version_id: UUID


async def entry_for_assessment(
    session: AsyncSession, *, report_version_id: UUID | None, project_id: UUID
) -> EntryForAssessment | None:
    """The project's entry in one submitted version, flattened to the text an assessment reads.

    `changed_in_version_id` is what decides whether a new assessment is due: an entry carried
    forward unchanged still points at the version its content last moved in (AC-17).
    """
    if report_version_id is None:
        return None
    entries = await repository.entries_of_version(session, report_version_id)
    entry = entries.get(project_id)
    if entry is None:
        return None

    parts = [
        entry.work_performed,
        entry.results,
        entry.deviations,
        entry.questions,
    ]
    return EntryForAssessment(
        id=entry.id,
        project_id=entry.project_id,
        stage=entry.stage,
        text="\n\n".join(part for part in parts if part),
        changed_in_version_id=entry.content_changed_in_version_id,
    )


@dataclass(frozen=True, slots=True)
class EntryForIndexing:
    id: UUID
    project_id: UUID
    stage: str
    text: str
    version_no: int
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """One submitted version, with the week and the timing it carries (REP-05)."""

    version_id: UUID
    report_id: UUID
    student_id: UUID
    period_id: UUID
    version_no: int
    submitted_at: datetime
    timing_status: str
    local_start: date
    local_end: date
    deadline_utc: datetime


@dataclass(frozen=True, slots=True)
class EntryRecord:
    """One project entry of a submitted version, as a question about the work would read it."""

    entry_id: UUID
    version_id: UUID
    student_id: UUID
    project_id: UUID
    period_id: UUID
    stage: str
    work_performed: str
    results: str
    deviations: str
    questions: str
    next_plan: dict[str, Any]
    submitted_at: datetime


async def ensure_periods_everywhere(session: AsyncSession) -> int:
    """REP-01: materialise the next weeks for every workspace, daily (architecture §12).

    A workspace with no calendar configured yet is skipped rather than treated as an error: the
    professor has not made that decision, and a daily log line saying so helps nobody.
    """
    created = 0
    for workspace_id in await identity_service.workspace_ids(session):
        scope = await identity_service.system_scope(session, workspace_id)
        try:
            periods = await ensure_periods(session, scope)
        except NotFoundError:
            continue
        for period in periods:
            await ensure_obligations(session, scope, period.id)
        created += len(periods)
    return created


async def freeze_due_baselines(session: AsyncSession, *, at: datetime | None = None) -> int:
    """PROJ-04: fix each membership's plan once its period has opened (architecture §12).

    Idempotent by construction — a membership that already has a baseline for the period keeps it —
    so this can run every day and re-cover a period the worker was down for.
    """
    instant = at or now()
    frozen = 0
    for workspace_id in await identity_service.workspace_ids(session):
        scope = await identity_service.system_scope(session, workspace_id)
        for period in await list_periods(session, scope):
            if period.start_utc > instant or period.end_utc < instant - BASELINE_CATCHUP:
                continue
            frozen += len(await freeze_baselines(session, scope, period.id))
    return frozen


async def submissions(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
) -> list[SubmissionRecord]:
    """Submitted versions the caller may read (QA-02).

    The assistant asks through this rather than reading the tables, so the timing counts it
    reports and the reports a student can open are filtered by the same predicate (AUTH-02).
    """
    rows = await repository.submitted_versions(
        session, scope, student_id=student_id, since=since, until=until, as_of=as_of
    )
    return [
        SubmissionRecord(
            version_id=version.id,
            report_id=report.id,
            student_id=report.student_id,
            period_id=report.period_id,
            version_no=version.version_no,
            submitted_at=version.submitted_at,
            timing_status=str(version.timing_status),
            local_start=period.local_start,
            local_end=period.local_end,
            deadline_utc=period.deadline_utc,
        )
        for version, report, period in rows
    ]


async def entries_in_range(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
) -> list[EntryRecord]:
    rows = await repository.entries_in_range(
        session,
        scope,
        student_id=student_id,
        project_id=project_id,
        since=since,
        until=until,
        as_of=as_of,
    )
    return [
        EntryRecord(
            entry_id=entry.id,
            version_id=version.id,
            student_id=report.student_id,
            project_id=entry.project_id,
            period_id=report.period_id,
            stage=str(entry.stage),
            work_performed=entry.work_performed,
            results=entry.results,
            deviations=entry.deviations,
            questions=entry.questions,
            next_plan=entry.next_plan,
            submitted_at=version.submitted_at,
        )
        for entry, version, report in rows
    ]


async def current_version_id_for_job(
    session: AsyncSession, *, student_id: UUID, period_id: UUID
) -> UUID | None:
    """Job-level read: the version a re-run should assess, or None if nothing was submitted."""
    report = (
        await session.execute(
            select(WeeklyReport.current_version_id).where(
                WeeklyReport.student_id == student_id, WeeklyReport.period_id == period_id
            )
        )
    ).scalar_one_or_none()
    return report


async def entry_ids_for_period(
    session: AsyncSession, *, student_id: UUID, project_id: UUID, period_id: UUID
) -> list[UUID]:
    """Job-level read: every version's entry for one student, project and week (ASSESS-01).

    A report entry belongs to a period by identity, not by when it was sent. The snapshot is built
    from a time window, which is right for repository work and wrong for this: a report submitted
    after the deadline has a `submitted_at` outside its own week, so a window alone would leave
    the student's own account of their work out of the assessment of it.
    """
    rows = await session.execute(
        select(ProjectReportEntry.id)
        .join(ReportVersion, ReportVersion.id == ProjectReportEntry.report_version_id)
        .join(WeeklyReport, WeeklyReport.id == ReportVersion.report_id)
        .where(
            WeeklyReport.student_id == student_id,
            WeeklyReport.period_id == period_id,
            ProjectReportEntry.project_id == project_id,
        )
    )
    return list(rows.scalars().all())


async def entries_for_indexing(
    session: AsyncSession, *, report_version_id: UUID
) -> list[EntryForIndexing]:
    """The entries of one submitted version, flattened for the evidence index (ASSESS-01)."""
    version = await session.get(ReportVersion, report_version_id)
    if version is None:
        return []

    entries = await repository.entries_of_version(session, report_version_id)
    flattened = []
    for entry in entries.values():
        parts = [
            entry.work_performed,
            entry.results,
            entry.deviations,
            entry.questions,
        ]
        text = "\n\n".join(part for part in parts if part)
        if not text.strip():
            continue
        flattened.append(
            EntryForIndexing(
                id=entry.id,
                project_id=entry.project_id,
                stage=entry.stage,
                text=text,
                version_no=version.version_no,
                submitted_at=version.submitted_at,
            )
        )
    return flattened


async def mark_reminder_dispatched(
    session: AsyncSession, period_id: UUID, *, at: datetime | None = None
) -> None:
    await repository.mark_reminder_dispatched(session, period_id, instant=at or now())
    await session.flush()


# ------------------------------------------------------------------ helpers


def _content_hash(payload: dict[str, Any]) -> bytes:
    """SHA-256 over the canonical JSON of the research content, excluding self-reported hours."""
    canonical = {field: payload.get(field) for field in CONTENT_FIELDS}
    return hashlib.sha256(
        orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS, default=str)
    ).digest()


def _carried_entry(previous: ProjectReportEntry, version_id: UUID) -> ProjectReportEntry:
    """A previous version's entry, copied onto a new version verbatim.

    `content_hash` and `content_changed_in_version_id` come across untouched, which is the point:
    nothing about the entry changed, so AC-17 keeps it pointing at the version it last changed in
    and no new assessment falls due for a project nobody wrote about this week.
    """
    return ProjectReportEntry(
        workspace_id=previous.workspace_id,
        report_version_id=version_id,
        project_id=previous.project_id,
        stage=previous.stage,
        milestone_ids=list(previous.milestone_ids or []),
        planned_work_ref=dict(previous.planned_work_ref or {}),
        work_performed=previous.work_performed,
        results=previous.results,
        experiments=list(previous.experiments or []),
        deviations=previous.deviations,
        next_plan=dict(previous.next_plan or {}),
        questions=previous.questions,
        evidence_refs=list(previous.evidence_refs or []),
        hours=previous.hours,
        content_hash=previous.content_hash,
        content_changed_in_version_id=previous.content_changed_in_version_id,
    )


def _check_package_is_complete(
    obligations: list[ReportingObligation], submitted: set[UUID]
) -> None:
    """REP-02: complete only when each required project has an entry or a recorded exemption."""
    required = {o.project_id for o in obligations if o.state is ObligationState.REQUIRED}
    missing = required - submitted
    if missing:
        raise ValidationError(
            "the package is missing an entry for every required project",
            missing_project_ids=[str(project_id) for project_id in sorted(missing, key=str)],
        )
    allowed = {o.project_id for o in obligations}
    unexpected = submitted - allowed
    if unexpected:
        raise ValidationError(
            "an entry names a project with no reporting obligation this period",
            unexpected_project_ids=[str(project_id) for project_id in sorted(unexpected, key=str)],
        )


def _entry_says_something(payload: dict[str, Any]) -> bool:
    """Whether this one entry has anything in it at all."""
    if any(
        str(payload.get(field) or "").strip()
        for field in ("work_performed", "results", "deviations", "questions")
    ):
        return True
    return bool(payload.get("next_plan")) or payload.get("hours") is not None


def _check_package_says_something(
    entries: list[dict[str, Any]], titles: dict[UUID, str] | None = None
) -> None:
    """An entry in which nothing was written is a mistake, not a week's work on that project.

    The editor recovers the autosaved draft, and a report submitted without one — the seed does
    this, and so does any client that posts entries directly — used to reopen as empty boxes over
    a version that had content. Pressing Submit then wrote that emptiness over the record, which
    is how this deployment acquired a version whose every field was blank. Refusing here is the
    half of the fix that does not depend on which screen the submission came from.

    This was once a test of the *package*: one non-empty field anywhere was enough, on the reading
    that judging a single entry's substance is the professor's job and not this function's. That
    reading still holds and is why the test is emptiness rather than adequacy — but at package
    level it let a wholly blank entry through whenever a sibling tab had text, and the obligation
    for that project was then marked satisfied. One press of one button could mark every project a
    student is on as reported, with nothing in any of them, and no screen anywhere said otherwise.
    So the same test now applies per entry, which is the granularity at which an obligation is
    discharged.
    """
    empty = [payload.get("project_id") for payload in entries if not _entry_says_something(payload)]
    if not empty:
        return
    if not entries:
        raise ValidationError("the package is empty — write something in at least one entry")
    named = ", ".join(
        (titles or {}).get(project_id, str(project_id)) for project_id in empty if project_id
    )
    raise ValidationError(
        f"nothing was written for {named or 'one of the projects'}"
        " — an entry with every box empty is not a report on that project",
        empty_project_ids=[str(project_id) for project_id in empty if project_id],
    )


def _timing_status(
    period: ReportingPeriod,
    obligations: list[ReportingObligation],
    at: datetime,
    *,
    grace_minutes: int = 0,
) -> TimingStatus:
    """REP-05/REP-06: the actual timestamp is kept either way; this only labels it.

    The grace comes from the period's own calendar configuration. It was hardcoded to zero here,
    which is `effective_deadline`'s only production call site, so a professor who configured
    thirty minutes of grace got none: a submission eleven minutes past the deadline was stamped
    LATE, and the missed-deadline notification had already gone out nine minutes before that.
    """
    if obligations and all(o.state is ObligationState.EXCUSED for o in obligations):
        return TimingStatus.EXCUSED
    extension = max(
        (o.extension_until_utc for o in obligations if o.extension_until_utc is not None),
        default=None,
    )
    deadline = calendar.effective_deadline(
        period.deadline_utc, grace_minutes=grace_minutes, extension_until_utc=extension
    )
    return TimingStatus.ON_TIME if at <= deadline else TimingStatus.LATE


async def grace_minutes_for(session: AsyncSession, period: ReportingPeriod) -> int:
    """The grace the professor configured for the calendar this period was cut from (REP-01)."""
    config = await repository.calendar_for(session, period.workspace_id, period.local_start)
    return 0 if config is None else config.grace_minutes


async def _next_version_no(session: AsyncSession, report: WeeklyReport) -> int:
    """One past the highest version this report has ever had (REP-05).

    From the highest, not from `current_version_id`. The two are normally the same, and when they
    are not — a current version rolled back to an earlier one, a restore, a correction applied by
    hand — counting from the current one reissues a number the table already holds, and
    `uq_report_versions_report_id_version_no` refuses the insert. The student then cannot submit
    that week again at all, and the only thing on screen is "that record already exists".

    REP-05 also settles which of the two is right: a resubmission *adds* to the history and never
    replaces it, so the sequence belongs to the history rather than to whichever version is being
    read today.
    """
    return await repository.highest_version_no(session, report.id) + 1


async def _resolve_open_revision_requests(
    session: AsyncSession, report_id: UUID, version_id: UUID
) -> None:
    from sqlalchemy import update

    await session.execute(
        update(RevisionRequest)
        .where(
            RevisionRequest.report_id == report_id,
            RevisionRequest.resolved_in_version_id.is_(None),
        )
        .values(resolved_in_version_id=version_id)
    )


async def _open_report(session: AsyncSession, scope: Scope, period_id: UUID) -> WeeklyReport:
    """The caller's own report for this period, created on first use."""
    if scope.role is not Role.STUDENT:
        raise ValidationError("only the student who owns the report may write to it")
    await _require_period(session, scope, period_id)

    report = await repository.get_report(
        session, scope, period_id=period_id, student_id=scope.user_id
    )
    if report is not None:
        return report

    obligations = await repository.list_obligations(
        session, scope, period_id, student_id=scope.user_id
    )
    if not obligations:
        raise ValidationError("no reporting obligation for this period")

    report = WeeklyReport(
        workspace_id=scope.workspace_id,
        student_id=scope.user_id,
        period_id=period_id,
        workflow_state=ReportState.DRAFT,
    )
    session.add(report)
    await session.flush()
    return report


async def _require_period(session: AsyncSession, scope: Scope, period_id: UUID) -> ReportingPeriod:
    period = await repository.get_period(session, scope, period_id)
    if period is None:
        raise NotFoundError("reporting period not found")
    return period


async def _require_obligation(
    session: AsyncSession, scope: Scope, obligation_id: UUID
) -> ReportingObligation:
    obligation = await repository.get_obligation(session, scope, obligation_id)
    if obligation is None:
        raise NotFoundError("reporting obligation not found")
    return obligation


async def _version_out(session: AsyncSession, scope: Scope, version: ReportVersion) -> VersionOut:
    entries = await repository.list_entries(session, scope, version.id)
    out = VersionOut.model_validate(version)
    return out.model_copy(update={"entries": [EntryOut.model_validate(e) for e in entries]})


def _audit(
    session: AsyncSession,
    scope: Scope,
    action: str,
    target_id: UUID,
    *,
    table: str = "reporting_obligations",
    after: dict[str, Any] | None = None,
) -> None:
    write_audit(
        session,
        scope=scope,
        action=action,
        target_table=table,
        target_id=target_id,
        after=after,
    )


async def _on_membership_started(event: Any, session: AsyncSession) -> None:
    """REP-01: derive the week's obligation as soon as somebody is on a project.

    Without this a project created on Tuesday owes nothing until `ensure_periods` runs at 00:15 the
    next morning — the student sees a project and no report, which reads as the system not having
    noticed. The nightly job stays: this is the same derivation brought forward, and running both
    is safe because `ensure_obligations` is idempotent per (membership, period).

    Runs under a system scope rather than the acting student's, because deriving obligations is a
    professor's act and a student has no standing to write one — the borrowed identity is what lets
    the same predicates apply here as to the scheduled run (ADR 0011).

    Whether the new membership actually owes *this* week is not decided here. That is
    `memberships_active_in_range`'s rule: a project started now owes the week it lands in, and a
    project joined now owes from the next one (PROJ-07). This function only makes the derivation
    happen at the right moment.
    """
    # `system_scope` always resolves: a workspace with no professor yet borrows its own id as a
    # value that names no user, which is what lets the calendar run before anyone has accepted.
    scope = await identity_service.system_scope(session, event.workspace_id)
    periods = await list_periods(session, scope)
    at = now()
    started = [period for period in periods if period.start_utc <= at]
    if not started:
        return  # No calendar, or none of its weeks has begun. The nightly run will catch up.

    await ensure_obligations(session, scope, max(started, key=lambda one: one.start_utc).id)


def register_subscriptions() -> None:
    """Imported for the side effect, like the other modules' (docs/repo_layout.md §3.2)."""
    from app.projects import events as projects_events

    projects_events.subscribe(projects_events.MembershipStarted, _on_membership_started)


register_subscriptions()
