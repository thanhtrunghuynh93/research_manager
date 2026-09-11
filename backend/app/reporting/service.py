"""Reporting use cases: calendar, obligations, drafts, and the submission lifecycle.

Requirements REP-01..06. Submission persists the work first and never blocks on anything external
(requirements §10): the version and its entries are written in one transaction, and jobs that read
them run afterwards.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import NotFoundError, ValidationError
from app.core.types import Role
from app.projects import service as projects_service
from app.projects.schemas import PlanBaselineOut
from app.reporting import calendar, events, policies, repository  # noqa: F401  (policies register)
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
)

# Eight weeks ahead, as the architecture's periodic task does (architecture §7.1).
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
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
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
            cursor, meeting_weekday=config.meeting_weekday, timezone=config.timezone
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
    rows = await repository.list_obligations(session, scope, period_id, student_id=student_id)
    return [ObligationOut.model_validate(row) for row in rows]


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

    items = entry.next_plan.get("items") if isinstance(entry.next_plan, dict) else None
    if not isinstance(items, list) or not items:
        return [], entry.id
    return [
        item for item in items if isinstance(item, dict) and item.get("planned_outcome")
    ], entry.id


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
    obligations = await repository.list_obligations(
        session, scope, period_id, student_id=report.student_id
    )
    submitted = {UUID(str(entry["project_id"])) for entry in entries}
    _check_package_is_complete(obligations, submitted)

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
        timing_status=_timing_status(period, obligations, at),
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
    session: AsyncSession, *, start: datetime, end: datetime
) -> list[PeriodOut]:
    rows = await repository.periods_with_deadline_between(session, start=start, end=end)
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

    for obligation in await repository.required_obligations_at(session, period_id, instant=instant):
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


def _timing_status(
    period: ReportingPeriod, obligations: list[ReportingObligation], at: datetime
) -> TimingStatus:
    """REP-05/REP-06: the actual timestamp is kept either way; this only labels it."""
    if obligations and all(o.state is ObligationState.EXCUSED for o in obligations):
        return TimingStatus.EXCUSED
    extension = max(
        (o.extension_until_utc for o in obligations if o.extension_until_utc is not None),
        default=None,
    )
    deadline = calendar.effective_deadline(
        period.deadline_utc, grace_minutes=0, extension_until_utc=extension
    )
    return TimingStatus.ON_TIME if at <= deadline else TimingStatus.LATE


async def _next_version_no(session: AsyncSession, report: WeeklyReport) -> int:
    if report.current_version_id is None:
        return 1
    current = await session.get(ReportVersion, report.current_version_id)
    return 1 if current is None else current.version_no + 1


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
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action=action,
        target_table=table,
        target_id=target_id,
        after=after,
    )
