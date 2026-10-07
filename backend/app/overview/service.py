"""What the professor overview reads (UI-01, REP-08, AC-13, AC-15).

Every number on the overview is computed here, from the tables, at an explicit instant: "three
missing" is not a fact without an as-of (AC-15). Each function returns plain rows, which the
endpoint shapes into its response; nothing here is written by a model.

These were fact functions of the chat assistant until it was withdrawn (ADR 0023). They moved here
unchanged in what they count, so the overview's numbers did not move with them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.core.errors import NotFoundError
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from app.reporting.models import ObligationState
from app.reporting.schemas import ObligationOut, PeriodOut

MISSING_NOTE = (
    "Counted from the reporting obligations after exemptions and extensions. An excused "
    "or extended obligation is not missing."
)


async def next_deadline(
    session: AsyncSession, scope: Scope, *, as_of: datetime
) -> dict[str, str] | None:
    """REP-01: 23:59 local on the day before the meeting. The timezone is part of the answer."""
    periods = await reporting_service.list_periods(session, scope)
    upcoming = [period for period in periods if period.deadline_utc >= as_of]
    if not upcoming:
        return None

    period = min(upcoming, key=lambda row: row.deadline_utc)
    return {
        "period_id": str(period.id),
        "local_start": period.local_start.isoformat(),
        "local_end": period.local_end.isoformat(),
        "meeting_date": period.meeting_date.isoformat(),
        "deadline_utc": period.deadline_utc.isoformat(),
        "timezone": await reporting_service.period_timezone(session, period.id),
    }


async def missing_reports(
    session: AsyncSession, scope: Scope, *, as_of: datetime
) -> list[dict[str, str]] | None:
    """AC-15: obligations minus submissions, after exemptions and extensions, as of an instant.

    The current week's. None when the workspace has no week yet, which the overview shows as
    nothing outstanding with no note, rather than as a counted zero.
    """
    period = await _current_period(session, scope, as_of=as_of)
    if period is None:
        return None

    entries = await reporting_service.unfulfilled_entries(session, period.id, at=as_of)
    return [
        {
            "student_id": str(entry.student_id),
            # The name, for the same reason the week's board carries one: a row identified by
            # eight characters of a uuid names nobody.
            "student_name": await display_name(session, scope, entry.student_id),
            "project_id": str(entry.project_id),
            "project_title": entry.project_title,
        }
        for entry in entries
    ]


async def week_reports(
    session: AsyncSession, scope: Scope, *, as_of: datetime
) -> list[dict[str, Any]]:
    """Every report owed this week, and whether it is in — by project and student.

    `missing_reports` answers half of this and is the half a professor cannot plan from: a list of
    absences says nothing about the week as a whole. This is the same obligations table read for
    its three states rather than one.
    """
    periods = await reporting_service.list_periods(session, scope)
    current: dict[UUID, PeriodOut] = {}
    for period in periods:
        if period.start_utc > as_of:
            continue
        running = current.get(period.workspace_id)
        if running is None or period.start_utc > running.start_utc:
            current[period.workspace_id] = period

    titles: dict[UUID, str] = {}
    names: dict[UUID, str] = {}
    rows: list[dict[str, Any]] = []

    for period in sorted(current.values(), key=lambda one: one.local_start):
        for obligation in await reporting_service.list_obligations(session, scope, period.id):
            if obligation.project_id not in titles:
                titles[obligation.project_id] = await projects_service.project_title(
                    session, obligation.project_id
                )
            if obligation.student_id not in names:
                names[obligation.student_id] = await display_name(
                    session, scope, obligation.student_id
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
    return rows


async def review_queue(
    session: AsyncSession, scope: Scope, *, as_of: datetime
) -> list[dict[str, Any]]:
    """UI-01: drafts waiting on the professor, named.

    Without the names the panel read "Draft for 01a0ad80" — and because these are UUIDv7 sharing
    a timestamp prefix, every draft showed the *same* eight characters.
    """
    drafts = await assessment_service.review_queue(session, scope, as_of=as_of)

    titles: dict[UUID, str] = {}
    names: dict[UUID, str] = {}
    for draft in drafts:
        if draft.project_id not in titles:
            titles[draft.project_id] = await projects_service.project_title(
                session, draft.project_id
            )
        if draft.student_id not in names:
            names[draft.student_id] = await display_name(session, scope, draft.student_id)

    return [
        {
            "assessment_id": str(draft.id),
            "student_id": str(draft.student_id),
            "student_name": names[draft.student_id],
            "project_id": str(draft.project_id),
            "project_title": titles[draft.project_id],
            "period_id": str(draft.period_id),
            "confidence": draft.confidence,
            "progress_index": draft.progress_index,
        }
        for draft in drafts
    ]


async def stalled_analyses(session: AsyncSession, scope: Scope) -> list[dict[str, str]]:
    """AC-13: a run that stopped short, and whether the cause was the model or the budget."""
    return [
        {
            "run_id": str(run.run_id),
            "student_id": str(run.student_id),
            "project_id": str(run.project_id),
            "period_id": str(run.period_id),
            "state": run.state,
            "reason": run.reason,
        }
        for run in await assessment_service.stalled_runs(session, scope)
    ]


async def display_name(session: AsyncSession, scope: Scope, student_id: UUID) -> str:
    """The student's name, or their id shortened when the caller may not read their user row.

    A professor reads every account in the workspace, so the fallback is for a row whose student
    has since left it: the overview still has to show something rather than fail.
    """
    try:
        return (await identity_service.get_user(session, scope, student_id)).display_name
    except NotFoundError:
        return str(student_id)[:8]


def _obligation_state(obligation: ObligationOut) -> str:
    """The three states a professor acts on differently (REP-06, REP-08).

    `state` says whether the project has to be in the package and never changes on submission;
    `submitted` is the other half.
    """
    if obligation.state is ObligationState.EXCUSED:
        return "excused"
    return "submitted" if obligation.submitted else "owed"


async def _current_period(
    session: AsyncSession, scope: Scope, *, as_of: datetime
) -> PeriodOut | None:
    """The week that started last, or the first one when none has started yet."""
    periods = await reporting_service.list_periods(session, scope)
    current = [period for period in periods if period.start_utc <= as_of]
    if not current:
        return periods[0] if periods else None
    return max(current, key=lambda row: row.start_utc)
