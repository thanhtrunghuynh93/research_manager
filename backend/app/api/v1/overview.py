"""The professor overview (UI-01).

One request behind one screen, assembled from the same fact functions the assistant uses. That is
deliberate: the number on the dashboard and the number in the answer are computed by the same
code, so they cannot disagree and then have to be reconciled by whoever is reading them.

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
from app.assistant import facts
from app.core.authz import Scope
from app.core.clock import now
from app.identity import service as identity_service
from app.notifications import service as notifications_service

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

    Grouped per workspace because a professor's reads span all of them (ADR 0016) and each keeps
    its own calendar — so "this week" is one period per workspace rather than one period.
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
    # AC-04: named as stale evidence, never rendered as an absence of work.
    sync_issues: list[dict[str, Any]] = Field(default_factory=list)
    # AC-13: runs that stopped short, with the reason, so a retry is an informed decision.
    stalled_analyses: list[dict[str, Any]] = Field(default_factory=list)
    ai_budget: BudgetState
    mail: MailState


@router.get("/overview", summary="The professor's current week at a glance")
async def overview(scope: ProfScopeDep, session: SessionDep) -> OverviewOut:
    as_of = now()
    query = facts.FactQuery(scope=scope, as_of=as_of)

    deadline = await facts.run(session, "next_deadline", query)
    outstanding = await facts.run(session, "missing_reports", query)
    week = await facts.run(session, "week_reports", query)
    queue = await facts.run(session, "review_queue", query)
    stale = await facts.run(session, "stale_repositories", query)
    stalled = await facts.run(session, "stalled_analyses", query)
    budgets = await ops.ai_budgets(session, scope)
    mail = await notifications_service.mail_health(session, scope)

    return OverviewOut(
        as_of=as_of,
        current_period=(
            CurrentPeriod(
                period_id=deadline.rows[0]["period_id"],
                local_start=deadline.rows[0]["local_start"],
                local_end=deadline.rows[0]["local_end"],
                meeting_date=deadline.rows[0]["meeting_date"],
                deadline_utc=deadline.rows[0]["deadline_utc"],
                timezone=deadline.rows[0]["timezone"],
            )
            if deadline is not None and deadline.rows
            else None
        ),
        outstanding=Outstanding(
            count=int(outstanding.value) if outstanding is not None else 0,
            as_of=as_of,
            entries=outstanding.rows if outstanding is not None else [],
            note=outstanding.note if outstanding is not None else "",
        ),
        week=await _week_board(session, scope, week),
        review_queue=queue.rows if queue is not None else [],
        sync_issues=stale.rows if stale is not None else [],
        stalled_analyses=stalled.rows if stalled is not None else [],
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
    session: AsyncSession, scope: Scope, week: facts.Fact | None
) -> list[WeekWorkspace]:
    """Group the flat fact rows into the shape the screen reads: workspace, project, student.

    The grouping is here rather than in the fact because the two callers want different shapes: the
    assistant cites rows, and a dashboard is a nesting. Both come from one computation, which is
    the rule this endpoint is built on — the number on the screen and the number in the answer
    cannot disagree if only one of them was ever computed.
    """
    if week is None or not week.rows:
        return []

    listed = await identity_service.list_workspaces(session, scope)
    names = {str(workspace.id): workspace.name for workspace in listed}
    boards: dict[str, WeekWorkspace] = {}
    projects: dict[tuple[str, str], WeekProject] = {}

    for row in week.rows:
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
