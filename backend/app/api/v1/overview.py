"""The professor overview (UI-01).

One request behind one screen. Every number on it is computed in `app.overview.service` from the
tables at the instant the request was served, and that instant is returned with it (AC-15).

Every section is always present, even when empty. A missing section reads as a broken screen; an
empty one reads as nothing to do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProfScopeDep, SessionDep
from app.assessment import ops
from app.core.authz import Scope
from app.core.clock import now
from app.identity import service as identity_service
from app.notifications import service as notifications_service
from app.overview import service as overview_service

router = APIRouter(tags=["overview"])


class CurrentPeriod(BaseModel):
    period_id: str
    local_start: str
    local_end: str
    meeting_date: str
    deadline_utc: str
    timezone: str


class Outstanding(BaseModel):
    """REP-08: who still owes a report, after exemptions and extensions, at a stated instant."""

    count: int
    as_of: datetime
    entries: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class WeekStudent(BaseModel):
    """One student's standing on one project this week, in the three states REP-06/REP-08 give."""

    student_id: str
    student_name: str
    state: str
    excuse_reason: str = ""
    extension_until_utc: str | None = None


class WeekProject(BaseModel):
    project_id: str
    project_title: str
    students: list[WeekStudent] = Field(default_factory=list)


class WeekWorkspace(BaseModel):
    """This week in one workspace: its period, and every report owed in it.

    A list of one since reads stopped spanning workspaces (ADR 0020, ADR 0021); the grouping is
    kept so the screen's shape did not change.
    """

    workspace_id: str
    workspace_name: str
    period_id: str
    local_start: str
    local_end: str
    submitted: int
    owed: int
    excused: int
    projects: list[WeekProject] = Field(default_factory=list)


class MailState(BaseModel):
    """UI-01: mail that did not arrive, named rather than left silent.

    An invitation that failed is the sharpest case — enrolment is invitation-only, so the person it
    was for has no way in at all, and nothing else on this screen would ever mention them.
    """

    warning: bool
    reason: str
    failed_notifications: int
    failed_token_emails: int


class BudgetState(BaseModel):
    analysis_delayed: bool
    warning: bool
    reason: str
    spent_usd: str
    monthly_usd: str | None = None


class OverviewOut(BaseModel):
    as_of: datetime
    current_period: CurrentPeriod | None = None
    outstanding: Outstanding
    # UI-01: the week as a whole, not only its absences. `outstanding` is the same obligations read
    # for one of their three states, and a list of absences is not something a supervisor can plan
    # from: a student who has reported does not appear in it at all.
    week: list[WeekWorkspace] = Field(default_factory=list)
    review_queue: list[dict[str, Any]] = Field(default_factory=list)
    # AC-13: runs that stopped short, with the reason, so a retry is an informed decision.
    stalled_analyses: list[dict[str, Any]] = Field(default_factory=list)
    ai_budget: BudgetState
    mail: MailState


@router.get("/overview", summary="The professor's current week at a glance")
async def overview(scope: ProfScopeDep, session: SessionDep) -> OverviewOut:
    as_of = now()

    deadline = await overview_service.next_deadline(session, scope, as_of=as_of)
    missing = await overview_service.missing_reports(session, scope, as_of=as_of)
    week = await overview_service.week_reports(session, scope, as_of=as_of)
    queue = await overview_service.review_queue(session, scope, as_of=as_of)
    stalled = await overview_service.stalled_analyses(session, scope)
    budgets = await ops.ai_budgets(session, scope)
    mail = await notifications_service.mail_health(session, scope)

    return OverviewOut(
        as_of=as_of,
        current_period=CurrentPeriod(**deadline) if deadline is not None else None,
        outstanding=Outstanding(
            count=len(missing) if missing is not None else 0,
            as_of=as_of,
            entries=missing if missing is not None else [],
            note=overview_service.MISSING_NOTE if missing is not None else "",
        ),
        week=await _week_board(session, scope, week),
        review_queue=queue,
        stalled_analyses=stalled,
        ai_budget=BudgetState(
            analysis_delayed=budgets.analysis_delayed,
            warning=budgets.warning,
            reason=budgets.reason,
            spent_usd=str(budgets.spent_usd),
            monthly_usd=budgets.monthly_usd,
        ),
        mail=MailState(
            warning=mail.warning,
            reason=mail.reason,
            failed_notifications=mail.failed_notifications,
            failed_token_emails=mail.failed_token_emails,
        ),
    )


async def _week_board(
    session: AsyncSession, scope: Scope, rows: list[dict[str, Any]]
) -> list[WeekWorkspace]:
    """Group the flat rows into the shape the screen reads: workspace, project, student."""
    if not rows:
        return []

    listed = await identity_service.list_workspaces(session, scope)
    names = {str(workspace.id): workspace.name for workspace in listed}
    boards: dict[str, WeekWorkspace] = {}
    projects: dict[tuple[str, str], WeekProject] = {}

    for row in rows:
        workspace_id = str(row["workspace_id"])
        board = boards.get(workspace_id)
        if board is None:
            board = WeekWorkspace(
                workspace_id=workspace_id,
                # A workspace they own but have left is not in the listing, and its rows still
                # have to say where they come from.
                workspace_name=names.get(workspace_id, ""),
                period_id=str(row["period_id"]),
                local_start=str(row["local_start"]),
                local_end=str(row["local_end"]),
                submitted=0,
                owed=0,
                excused=0,
            )
            boards[workspace_id] = board

        key = (workspace_id, str(row["project_id"]))
        project = projects.get(key)
        if project is None:
            project = WeekProject(
                project_id=str(row["project_id"]), project_title=str(row["project_title"])
            )
            projects[key] = project
            board.projects.append(project)

        state = str(row["state"])
        project.students.append(
            WeekStudent(
                student_id=str(row["student_id"]),
                student_name=str(row["student_name"]),
                state=state,
                excuse_reason=str(row.get("excuse_reason") or ""),
                extension_until_utc=row.get("extension_until_utc"),
            )
        )
        setattr(board, state, getattr(board, state) + 1)

    # Stable and readable: projects by title, students by name, so the board does not reorder
    # itself between two loads of the same week.
    for board in boards.values():
        board.projects.sort(key=lambda one: one.project_title.lower())
        for project in board.projects:
            project.students.sort(key=lambda one: one.student_name.lower())
    return sorted(boards.values(), key=lambda one: one.workspace_name.lower())
