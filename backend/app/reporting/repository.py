"""Queries over reporting tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.reporting.models import (
    CalendarConfig,
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
