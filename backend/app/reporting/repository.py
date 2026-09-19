"""Queries over reporting tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.reporting.models import (
    CalendarConfig,
    ObligationState,
    ProjectReportEntry,
    ReportingObligation,
    ReportingPeriod,
    ReportVersion,
    RevisionRequest,
    WeeklyReport,
)


async def latest_calendar(session: AsyncSession, workspace_id: UUID) -> CalendarConfig | None:
    return (
        await session.execute(
            select(CalendarConfig)
            .where(CalendarConfig.workspace_id == workspace_id)
            .order_by(CalendarConfig.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def calendar_for(
    session: AsyncSession, workspace_id: UUID, local_start: date
) -> CalendarConfig | None:
    """REP-01: the configuration whose effective_from is the latest not after the period start."""
    return (
        await session.execute(
            select(CalendarConfig)
            .where(
                CalendarConfig.workspace_id == workspace_id,
                CalendarConfig.effective_from <= local_start,
            )
            .order_by(CalendarConfig.effective_from.desc(), CalendarConfig.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def last_period(session: AsyncSession, workspace_id: UUID) -> ReportingPeriod | None:
    return (
        await session.execute(
            select(ReportingPeriod)
            .where(ReportingPeriod.workspace_id == workspace_id)
            .order_by(ReportingPeriod.local_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def period_before(
    session: AsyncSession, workspace_id: UUID, local_start: date
) -> ReportingPeriod | None:
    return (
        await session.execute(
            select(ReportingPeriod)
            .where(
                ReportingPeriod.workspace_id == workspace_id,
                ReportingPeriod.local_start < local_start,
            )
            .order_by(ReportingPeriod.local_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_periods(
    session: AsyncSession, scope: Scope, *, through: date | None = None
) -> list[ReportingPeriod]:
    statement = (
        select(ReportingPeriod)
        .where(visible_to(scope, ReportingPeriod))
        .order_by(ReportingPeriod.local_start)
    )
    if through is not None:
        statement = statement.where(ReportingPeriod.local_start <= through)
    return list((await session.execute(statement)).scalars().all())


async def get_period(
    session: AsyncSession, scope: Scope, period_id: UUID
) -> ReportingPeriod | None:
    return (
        await session.execute(
            select(ReportingPeriod).where(
                ReportingPeriod.id == period_id, visible_to(scope, ReportingPeriod)
            )
        )
    ).scalar_one_or_none()


async def get_period_unscoped(session: AsyncSession, period_id: UUID) -> ReportingPeriod | None:
    """One period, without a Scope — for REP-08's job-level reads.

    Unscoped for the same reason `required_obligations_at` is: the missed-deadline sweep and the
    professor's outstanding list are computed for a period across every student in it, and there
    is no one caller whose visibility would be the right filter.
    """
    return (
        await session.execute(select(ReportingPeriod).where(ReportingPeriod.id == period_id))
    ).scalar_one_or_none()


async def list_obligations(
    session: AsyncSession, scope: Scope, period_id: UUID, *, student_id: UUID | None = None
) -> list[ReportingObligation]:
    statement = (
        select(ReportingObligation)
        .where(ReportingObligation.period_id == period_id, visible_to(scope, ReportingObligation))
        .order_by(ReportingObligation.id)
    )
    if student_id is not None:
        statement = statement.where(ReportingObligation.student_id == student_id)
    return list((await session.execute(statement)).scalars().all())


async def get_obligation(
    session: AsyncSession, scope: Scope, obligation_id: UUID
) -> ReportingObligation | None:
    return (
        await session.execute(
            select(ReportingObligation).where(
                ReportingObligation.id == obligation_id, visible_to(scope, ReportingObligation)
            )
        )
    ).scalar_one_or_none()


async def obligation_for_membership(
    session: AsyncSession, membership_id: UUID, period_id: UUID
) -> ReportingObligation | None:
    return (
        await session.execute(
            select(ReportingObligation).where(
                ReportingObligation.membership_id == membership_id,
                ReportingObligation.period_id == period_id,
            )
        )
    ).scalar_one_or_none()


async def period_row(session: AsyncSession, period_id: UUID) -> ReportingPeriod | None:
    """Job-level read: the worker has no Scope, and a period is workspace-wide anyway."""
    return await session.get(ReportingPeriod, period_id)


async def periods_awaiting_reminder(
    session: AsyncSession, *, instant: datetime
) -> list[ReportingPeriod]:
    """REP-08: periods whose reminder is due and has not been dispatched."""
    return list(
        (
            await session.execute(
                select(ReportingPeriod)
                .where(
                    ReportingPeriod.reminder_due_utc <= instant,
                    ReportingPeriod.reminder_dispatched_at.is_(None),
                )
                .order_by(ReportingPeriod.reminder_due_utc)
            )
        )
        .scalars()
        .all()
    )


async def periods_with_deadline_between(
    session: AsyncSession, *, start: datetime, end: datetime, workspace_id: UUID | None = None
) -> list[ReportingPeriod]:
    """Job-level read across workspaces; `workspace_id` narrows it to one."""
    query = select(ReportingPeriod).where(
        ReportingPeriod.deadline_utc > start, ReportingPeriod.deadline_utc <= end
    )
    if workspace_id is not None:
        query = query.where(ReportingPeriod.workspace_id == workspace_id)
    return list((await session.execute(query)).scalars().all())


async def required_obligations_at(
    session: AsyncSession, period_id: UUID, *, instant: datetime
) -> list[ReportingObligation]:
    """Required, not excused, and with no extension still running at `instant` (REP-08)."""
    return list(
        (
            await session.execute(
                select(ReportingObligation)
                .where(
                    ReportingObligation.period_id == period_id,
                    ReportingObligation.state == ObligationState.REQUIRED,
                    or_(
                        ReportingObligation.extension_until_utc.is_(None),
                        ReportingObligation.extension_until_utc <= instant,
                    ),
                )
                .order_by(ReportingObligation.student_id, ReportingObligation.id)
            )
        )
        .scalars()
        .all()
    )


async def submitted_project_ids(
    session: AsyncSession, *, period_id: UUID, student_id: UUID
) -> set[UUID]:
    """The projects this student's current version actually carries an entry for."""
    report = (
        await session.execute(
            select(WeeklyReport).where(
                WeeklyReport.period_id == period_id, WeeklyReport.student_id == student_id
            )
        )
    ).scalar_one_or_none()
    if report is None or report.current_version_id is None:
        return set()
    rows = await session.execute(
        select(ProjectReportEntry.project_id).where(
            ProjectReportEntry.report_version_id == report.current_version_id
        )
    )
    return set(rows.scalars().all())


async def mark_reminder_dispatched(
    session: AsyncSession, period_id: UUID, *, instant: datetime
) -> None:
    await session.execute(
        update(ReportingPeriod)
        .where(ReportingPeriod.id == period_id, ReportingPeriod.reminder_dispatched_at.is_(None))
        .values(reminder_dispatched_at=instant)
    )


async def get_report(
    session: AsyncSession, scope: Scope, *, period_id: UUID, student_id: UUID
) -> WeeklyReport | None:
    return (
        await session.execute(
            select(WeeklyReport).where(
                WeeklyReport.period_id == period_id,
                WeeklyReport.student_id == student_id,
                visible_to(scope, WeeklyReport),
            )
        )
    ).scalar_one_or_none()


async def get_report_by_id(
    session: AsyncSession, scope: Scope, report_id: UUID
) -> WeeklyReport | None:
    return (
        await session.execute(
            select(WeeklyReport).where(
                WeeklyReport.id == report_id, visible_to(scope, WeeklyReport)
            )
        )
    ).scalar_one_or_none()


async def version_by_idempotency_key(
    session: AsyncSession, report_id: UUID, key: str
) -> ReportVersion | None:
    return (
        await session.execute(
            select(ReportVersion).where(
                ReportVersion.report_id == report_id, ReportVersion.idempotency_key == key
            )
        )
    ).scalar_one_or_none()


async def highest_version_no(session: AsyncSession, report_id: UUID) -> int:
    """The largest `version_no` this report carries, or 0 when it has none.

    Unscoped and read straight from the versions, because it answers a question about the table's
    own unique constraint rather than about what a caller may see.
    """
    return (
        await session.execute(
            select(func.coalesce(func.max(ReportVersion.version_no), 0)).where(
                ReportVersion.report_id == report_id
            )
        )
    ).scalar_one()


async def get_version(
    session: AsyncSession, scope: Scope, version_id: UUID
) -> ReportVersion | None:
    return (
        await session.execute(
            select(ReportVersion).where(
                ReportVersion.id == version_id, visible_to(scope, ReportVersion)
            )
        )
    ).scalar_one_or_none()


async def list_entries(
    session: AsyncSession, scope: Scope, version_id: UUID
) -> list[ProjectReportEntry]:
    return list(
        (
            await session.execute(
                select(ProjectReportEntry)
                .where(
                    ProjectReportEntry.report_version_id == version_id,
                    visible_to(scope, ProjectReportEntry),
                )
                .order_by(ProjectReportEntry.id)
            )
        )
        .scalars()
        .all()
    )


async def entries_of_version(
    session: AsyncSession, version_id: UUID
) -> dict[UUID, ProjectReportEntry]:
    """Service-internal: the previous version's entries, keyed by project, to compare hashes."""
    rows = (
        await session.execute(
            select(ProjectReportEntry).where(ProjectReportEntry.report_version_id == version_id)
        )
    ).scalars()
    return {row.project_id: row for row in rows}


async def list_revision_requests(
    session: AsyncSession, scope: Scope, report_id: UUID
) -> list[RevisionRequest]:
    return list(
        (
            await session.execute(
                select(RevisionRequest)
                .where(
                    RevisionRequest.report_id == report_id,
                    visible_to(scope, RevisionRequest),
                )
                .order_by(RevisionRequest.created_at)
            )
        )
        .scalars()
        .all()
    )


async def submitted_versions(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
) -> list[tuple[ReportVersion, WeeklyReport, ReportingPeriod]]:
    """Submitted versions the caller may read, bounded by when they were submitted.

    `as_of` is the historical cut: a question about 1 September must not see a version submitted
    on the 5th (QA-04).
    """
    statement = (
        select(ReportVersion, WeeklyReport, ReportingPeriod)
        .join(WeeklyReport, WeeklyReport.id == ReportVersion.report_id)
        .join(ReportingPeriod, ReportingPeriod.id == WeeklyReport.period_id)
        .where(visible_to(scope, ReportVersion))
        .order_by(ReportVersion.submitted_at)
    )
    if student_id is not None:
        statement = statement.where(WeeklyReport.student_id == student_id)
    if since is not None:
        statement = statement.where(ReportVersion.submitted_at >= since)
    if until is not None:
        statement = statement.where(ReportVersion.submitted_at <= until)
    if as_of is not None:
        statement = statement.where(ReportVersion.submitted_at <= as_of)
    return [tuple(row) for row in (await session.execute(statement)).all()]


async def entries_in_range(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
) -> list[tuple[ProjectReportEntry, ReportVersion, WeeklyReport]]:
    statement = (
        select(ProjectReportEntry, ReportVersion, WeeklyReport)
        .join(ReportVersion, ReportVersion.id == ProjectReportEntry.report_version_id)
        .join(WeeklyReport, WeeklyReport.id == ReportVersion.report_id)
        .where(visible_to(scope, ProjectReportEntry))
        .order_by(ReportVersion.submitted_at)
    )
    if student_id is not None:
        statement = statement.where(WeeklyReport.student_id == student_id)
    if project_id is not None:
        statement = statement.where(ProjectReportEntry.project_id == project_id)
    if since is not None:
        statement = statement.where(ReportVersion.submitted_at >= since)
    if until is not None:
        statement = statement.where(ReportVersion.submitted_at <= until)
    if as_of is not None:
        statement = statement.where(ReportVersion.submitted_at <= as_of)
    return [tuple(row) for row in (await session.execute(statement)).all()]
