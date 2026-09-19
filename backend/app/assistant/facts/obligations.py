"""Facts about who owed a report and when (REP-01, REP-06, REP-08, AC-15).

"Which reports are missing?" is the question the assistant is most likely to be asked and most
likely to get wrong if it answers from narrative text. The authority is the obligations table after
exemptions and extensions, read at an explicit instant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.facts.base import Citation, Fact, FactQuery, display_name, fact
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from app.reporting.models import ObligationState
from app.reporting.schemas import ObligationOut, PeriodOut


@fact("missing_reports")
async def missing_reports(session: AsyncSession, query: FactQuery) -> Fact | None:
    """AC-15: obligations minus submissions, after exemptions and extensions, as of an instant.

    A student asking this sees only their own row, because `list_obligations` compiles the same
    predicate every other read of an obligation does (AUTH-02).
    """
    period = await _period(session, query)
    if period is None:
        return None

    entries = await reporting_service.unfulfilled_entries(session, period.id, at=query.as_of)
    if not query.scope.is_prof:
        entries = [entry for entry in entries if entry.student_id == query.scope.user_id]
    if query.student_id is not None:
        entries = [entry for entry in entries if entry.student_id == query.student_id]

    return Fact(
        name="missing_reports",
        label=f"Unfulfilled reporting obligations for the week of {period.local_start}",
        value=len(entries),
        as_of=query.as_of,
        rows=[
            {
                "student_id": str(entry.student_id),
                # The name, for the same reason the week's board carries one: a row identified by
                # eight characters of a uuid names nobody, and this list sits directly under a
                # board that does name them.
                "student_name": await display_name(session, query, entry.student_id),
                "project_id": str(entry.project_id),
                "project_title": entry.project_title,
            }
            for entry in entries
        ],
        citations=[
            Citation(
                source_kind="reporting_period",
                source_id=period.id,
                locator=f"/report/{period.id}",
                label=f"week of {period.local_start} to {period.local_end}",
            )
        ],
        note=(
            "Counted from the reporting obligations after exemptions and extensions. An excused "
            "or extended obligation is not missing."
        ),
    )


@fact("week_reports")
async def week_reports(session: AsyncSession, query: FactQuery) -> Fact | None:
    """Every report owed this week, and whether it is in — by workspace, project and student.

    `missing_reports` answers half of this and is the half a professor cannot plan from: a list of
    absences says nothing about the week as a whole, and a student who has reported is invisible in
    it. This is the same obligations table read for its three states rather than one.

    One period **per workspace**, because a professor's reads span every workspace they belong to
    (ADR 0016) and each keeps its own calendar, so there is no single "this week" for them.

    A student reaching this sees only their own rows, as every other read of an obligation does:
    `list_obligations` compiles the same predicate (AUTH-02).
    """
    periods = await reporting_service.list_periods(session, query.scope)
    current: dict[UUID, PeriodOut] = {}
    for period in periods:
        if period.start_utc > query.as_of:
            continue
        running = current.get(period.workspace_id)
        if running is None or period.start_utc > running.start_utc:
            current[period.workspace_id] = period
    if query.period_id is not None:
        current = {
            workspace_id: period
            for workspace_id, period in current.items()
            if period.id == query.period_id
        }
    if not current:
        return None

    titles: dict[UUID, str] = {}
    names: dict[UUID, str] = {}
    rows: list[dict[str, Any]] = []

    for period in sorted(current.values(), key=lambda one: one.local_start):
        for obligation in await reporting_service.list_obligations(session, query.scope, period.id):
            if query.student_id is not None and obligation.student_id != query.student_id:
                continue
            if obligation.project_id not in titles:
                titles[obligation.project_id] = await projects_service.project_title(
                    session, obligation.project_id
                )
            if obligation.student_id not in names:
                names[obligation.student_id] = await display_name(
                    session, query, obligation.student_id
                )
            rows.append(
                {
                    "workspace_id": str(period.workspace_id),
                    "period_id": str(period.id),
                    "local_start": period.local_start.isoformat(),
                    "local_end": period.local_end.isoformat(),
                    "project_id": str(obligation.project_id),
                    "project_title": titles[obligation.project_id],
                    "student_id": str(obligation.student_id),
                    "student_name": names[obligation.student_id],
                    "state": _obligation_state(obligation),
                    "excuse_reason": obligation.excuse_reason or "",
                    "extension_until_utc": (
                        obligation.extension_until_utc.isoformat()
                        if obligation.extension_until_utc is not None
                        else None
                    ),
                }
            )

    submitted = sum(1 for row in rows if row["state"] == "submitted")
    return Fact(
        name="week_reports",
        label="Reports owed this week, and which of them are in",
        value=f"{submitted} of {len(rows)}",
        as_of=query.as_of,
        rows=rows,
        citations=[
            Citation(
                source_kind="reporting_period",
                source_id=period.id,
                locator=f"/report/{period.id}",
                label=f"week of {period.local_start} to {period.local_end}",
            )
            for period in sorted(current.values(), key=lambda one: one.local_start)
        ],
        note=(
            "One row per reporting obligation, so an excused or extended one is listed and marked "
            "rather than counted as owed. Submission is read from the report's current version."
        ),
    )


def _obligation_state(obligation: ObligationOut) -> str:
    """The three states a professor acts on differently (REP-06, REP-08).

    `state` says whether the project has to be in the package and never changes on submission;
    `submitted` is the other half. Collapsing them here rather than on the screen keeps the
    dashboard and the assistant saying the same word for the same row.
    """
    if obligation.state is ObligationState.EXCUSED:
        return "excused"
    return "submitted" if obligation.submitted else "owed"


@fact("next_deadline")
async def next_deadline(session: AsyncSession, query: FactQuery) -> Fact | None:
    """REP-01: 23:59 local on the day before the meeting. The timezone is part of the answer."""
    periods = await reporting_service.list_periods(session, query.scope)
    upcoming = [period for period in periods if period.deadline_utc >= query.as_of]
    if not upcoming:
        return None

    period = min(upcoming, key=lambda row: row.deadline_utc)
    timezone = await reporting_service.period_timezone(session, period.id)
    return Fact(
        name="next_deadline",
        label="Next reporting deadline",
        value=period.deadline_utc.isoformat(),
        as_of=query.as_of,
        rows=[
            {
                "period_id": str(period.id),
                "local_start": period.local_start.isoformat(),
                "local_end": period.local_end.isoformat(),
                "meeting_date": period.meeting_date.isoformat(),
                "deadline_utc": period.deadline_utc.isoformat(),
                "timezone": timezone,
            }
        ],
        citations=[
            Citation(
                source_kind="reporting_period",
                source_id=period.id,
                locator=f"/report/{period.id}",
                label=f"week of {period.local_start} to {period.local_end}",
            )
        ],
        note=f"Local time in {timezone}; the deadline is 23:59 on the day before the meeting.",
    )


@fact("timing_counts")
async def timing_counts(session: AsyncSession, query: FactQuery) -> Fact:
    """REP-05: on time, late, or excused — counted from the versions, never from prose."""
    records = await reporting_service.submissions(
        session,
        query.scope,
        student_id=query.student_id,
        since=query.since,
        until=query.until,
        as_of=query.as_of,
    )
    # One report may have several versions; the timing question is about the report, and the first
    # submission is the one whose timestamp is never rewritten (REP-07, AC-13).
    first_by_report: dict[str, str] = {}
    for record in sorted(records, key=lambda row: row.version_no):
        first_by_report.setdefault(str(record.report_id), record.timing_status)

    counts: dict[str, int] = {}
    for status in first_by_report.values():
        counts[status] = counts.get(status, 0) + 1

    return Fact(
        name="timing_counts",
        label="Submissions by timing status",
        value=counts,
        as_of=query.as_of,
        rows=[
            {"timing_status": status, "count": count} for status, count in sorted(counts.items())
        ],
        note=(
            "Counted from each report's first submission, whose timestamp is never rewritten "
            "by a later revision."
        ),
    )


async def _period(session: AsyncSession, query: FactQuery) -> PeriodOut | None:
    if query.period_id is not None:
        return await reporting_service.period_for_job(session, query.period_id)
    periods = await reporting_service.list_periods(session, query.scope)
    current = [period for period in periods if period.start_utc <= query.as_of]
    if not current:
        return periods[0] if periods else None
    return max(current, key=lambda row: row.start_utc)
