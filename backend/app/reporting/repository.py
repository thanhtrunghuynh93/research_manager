"""Queries over reporting tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.errors import ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.identity.models import User
from app.reporting.models import (
    CalendarConfig,
    ObligationState,
    ProjectReportEntry,
    ReportingObligation,
    ReportingPeriod,
    ReportState,
    ReportVersion,
    RevisionRequest,
    WeeklyReport,
)

# One row of the submitted-reports list: the report, its week, the student's name, how many
# versions it has, and when the newest of them was handed in.
SubmittedReportRow = tuple[WeeklyReport, ReportingPeriod, str, int, datetime]


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


async def unstarted_periods(
    session: AsyncSession, workspace_id: UUID, *, after: datetime, from_local: date
) -> list[ReportingPeriod]:
    """Opened weeks that have not begun yet, from `from_local` on — the ones a new calendar may
    still re-date, because no report can have been written against a week that has not started."""
    return list(
        (
            await session.execute(
                select(ReportingPeriod)
                .where(
                    ReportingPeriod.workspace_id == workspace_id,
                    ReportingPeriod.start_utc > after,
                    ReportingPeriod.local_start >= from_local,
                )
                .order_by(ReportingPeriod.local_start)
            )
        )
        .scalars()
        .all()
    )


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
    session: AsyncSession,
    scope: Scope,
    *,
    through: date | None = None,
) -> list[ReportingPeriod]:
    """The weeks of the workspace the caller is working in, oldest first.

    `local_start` is unique per workspace, so with one workspace it is a total order.
    """
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


async def list_versions(
    session: AsyncSession, scope: Scope, report_id: UUID
) -> list[ReportVersion]:
    """Every submitted version of one report, oldest first.

    Until this existed a version was reachable only by its id, and the only id anyone held was
    `current_version_id` — so REP-05's "a resubmission adds a version and never replaces history"
    had no reader on either side of the product.
    """
    return list(
        (
            await session.execute(
                select(ReportVersion)
                .where(
                    ReportVersion.report_id == report_id,
                    visible_to(scope, ReportVersion),
                )
                .order_by(ReportVersion.version_no)
            )
        )
        .scalars()
        .all()
    )


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


async def list_submitted_reports(
    session: AsyncSession,
    scope: Scope,
    *,
    limit: int,
    cursor: str | None,
    period_id: UUID | None = None,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    states: Collection[ReportState] | None = None,
) -> tuple[list[SubmittedReportRow], str | None]:
    """Reports handed in at least once, newest week first, then by student name (UI-01, UI-04).

    A draft is never listed, to anyone: `first_submitted_at` is the line between the student's
    working copy and the record. The order is a keyset on (week, name, id), so a page boundary
    cannot drop or repeat a row when a name or a week is shared.

    The version count and the newest submission are correlated subqueries rather than a grouped
    join, so they are computed for the page and not for every report in the workspace. The
    versions are read through their report, which the visibility predicate has already admitted.
    """
    version_count = (
        select(func.count(ReportVersion.id))
        .where(ReportVersion.report_id == WeeklyReport.id)
        .correlate(WeeklyReport)
        .scalar_subquery()
    )
    last_submitted = (
        select(func.max(ReportVersion.submitted_at))
        .where(ReportVersion.report_id == WeeklyReport.id)
        .correlate(WeeklyReport)
        .scalar_subquery()
    )
    statement = (
        select(WeeklyReport, ReportingPeriod, User.display_name, version_count, last_submitted)
        .join(ReportingPeriod, ReportingPeriod.id == WeeklyReport.period_id)
        # Joined rather than read through identity's service, because the list is ordered by it and
        # a keyset page has to be cut in SQL — as `projects.repository.list_memberships` joins it.
        .join(User, User.id == WeeklyReport.student_id)
        .where(visible_to(scope, WeeklyReport), WeeklyReport.first_submitted_at.is_not(None))
        .order_by(ReportingPeriod.local_start.desc(), User.display_name, WeeklyReport.id)
    )
    if period_id is not None:
        statement = statement.where(WeeklyReport.period_id == period_id)
    if student_id is not None:
        statement = statement.where(WeeklyReport.student_id == student_id)
    if states is not None:
        statement = statement.where(WeeklyReport.workflow_state.in_(list(states)))
    if project_id is not None:
        # The project as the current version has it: an entry carried forward still counts.
        statement = statement.where(
            select(ProjectReportEntry.id)
            .where(
                ProjectReportEntry.report_version_id == WeeklyReport.current_version_id,
                ProjectReportEntry.project_id == project_id,
            )
            .exists()
        )
    position = _report_list_position(cursor)
    if position is not None:
        local_start, name, after = position
        statement = statement.where(
            or_(
                ReportingPeriod.local_start < local_start,
                and_(
                    ReportingPeriod.local_start == local_start,
                    or_(
                        User.display_name > name,
                        and_(User.display_name == name, WeeklyReport.id > after),
                    ),
                ),
            )
        )

    rows: list[SubmittedReportRow] = [
        (report, period, name, int(count), last)
        for report, period, name, count, last in await session.execute(statement.limit(limit + 1))
    ]
    if len(rows) <= limit:
        return rows, None
    report, period, name, _, _ = rows[limit - 1]
    return rows[:limit], encode_cursor(
        {"local_start": period.local_start.isoformat(), "name": name, "after": str(report.id)}
    )


def _report_list_position(cursor: str | None) -> tuple[date, str, UUID] | None:
    """Where a page of the report list resumes; a malformed cursor is a 422, not a 500."""
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    try:
        return (
            date.fromisoformat(str(decoded["local_start"])),
            str(decoded["name"]),
            UUID(str(decoded["after"])),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc


async def projects_of_versions(
    session: AsyncSession, scope: Scope, version_ids: Collection[UUID]
) -> dict[UUID, list[UUID]]:
    """The projects each of these versions has an entry for, in one query."""
    if not version_ids:
        return {}
    rows = await session.execute(
        select(ProjectReportEntry.report_version_id, ProjectReportEntry.project_id).where(
            ProjectReportEntry.report_version_id.in_(list(version_ids)),
            visible_to(scope, ProjectReportEntry),
        )
    )
    out: dict[UUID, list[UUID]] = {}
    for version_id, project_id in rows:
        out.setdefault(version_id, []).append(project_id)
    return out


async def obligations_for_weeks(
    session: AsyncSession, scope: Scope, weeks: Sequence[tuple[UUID, UUID]]
) -> dict[tuple[UUID, UUID], list[ReportingObligation]]:
    """Every obligation of these (student, period) pairs, in one query, keyed by the pair."""
    if not weeks:
        return {}
    rows = (
        await session.execute(
            select(ReportingObligation).where(
                tuple_(ReportingObligation.student_id, ReportingObligation.period_id).in_(
                    list(weeks)
                ),
                visible_to(scope, ReportingObligation),
            )
        )
    ).scalars()
    out: dict[tuple[UUID, UUID], list[ReportingObligation]] = {}
    for row in rows:
        out.setdefault((row.student_id, row.period_id), []).append(row)
    return out


async def calendars(session: AsyncSession, workspace_id: UUID) -> list[CalendarConfig]:
    """Every calendar version of the workspace. A handful of rows, read once per list page."""
    return list(
        (
            await session.execute(
                select(CalendarConfig).where(CalendarConfig.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
