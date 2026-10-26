"""The read-only tools a connector may call (ADR 0025).

Each tool is a thin call into a service function with the professor's Scope, so what it returns is
exactly what the same professor sees in the app: the visibility predicates do the filtering, and
nothing here widens them. A tool takes a pydantic model for its arguments, which gives the client a
JSON Schema and validates the call in one place.

Tools that return text students wrote say so (`quotes_student_text`): the server prefixes their
result with a notice that the text is quoted data, since it ends up in a model's context.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.core.clock import now
from app.identity import service as identity_service
from app.overview import service as overview_service
from app.projects import service as projects_service
from app.projects.schemas import ProjectStatus
from app.reporting import artifacts as artifacts_service
from app.reporting import service as reporting_service
from app.reporting.schemas import ReportState

Handler = Callable[[AsyncSession, Scope, Any], Awaitable[Any]]

LIMIT = Field(default=None, ge=1, le=200, description="Page size, at most 200.")
CURSOR = Field(default=None, description="`next_cursor` from the previous page.")


class WorkspaceArgs(BaseModel):
    """Every tool takes this: which of the professor's workspaces to read."""

    workspace_id: UUID | None = Field(
        default=None,
        description="Which workspace (lab) to read. Omit for the default; "
        "list_workspaces shows every one you can name.",
    )


class NoArgs(WorkspaceArgs):
    pass


class PageArgs(WorkspaceArgs):
    limit: int | None = LIMIT
    cursor: str | None = CURSOR


class ListProjectsArgs(PageArgs):
    status: ProjectStatus | None = None


class ListPeriodsArgs(WorkspaceArgs):
    through: date | None = Field(default=None, description="Weeks up to this date, ISO format.")


class ListObligationsArgs(WorkspaceArgs):
    period_id: UUID
    student_id: UUID | None = None


class ListReportsArgs(PageArgs):
    period_id: UUID | None = None
    student_id: UUID | None = None
    project_id: UUID | None = None
    state: list[ReportState] | None = None
    needs_review: bool = Field(
        default=False, description="Only reports submitted or resubmitted and not yet reviewed."
    )


class VersionArgs(WorkspaceArgs):
    version_id: UUID


class ReportArgs(WorkspaceArgs):
    report_id: UUID


class ListAssessmentsArgs(WorkspaceArgs):
    student_id: UUID | None = None
    project_id: UUID | None = None
    period_id: UUID | None = None


class AssessmentArgs(WorkspaceArgs):
    assessment_id: UUID


class TrendArgs(WorkspaceArgs):
    student_id: UUID
    project_id: UUID


class ListAttachmentsArgs(WorkspaceArgs):
    student_id: UUID | None = None
    project_id: UUID | None = None
    period_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    quotes_student_text: bool = False


class ListWorkspacesArgs(BaseModel):
    pass


async def _list_workspaces(session: AsyncSession, scope: Scope, _: ListWorkspacesArgs) -> Any:
    return {
        "default_workspace_id": scope.workspace_id,
        "workspaces": await identity_service.joined_workspaces(session, scope),
    }


async def _whoami(session: AsyncSession, scope: Scope, _: NoArgs) -> Any:
    user = await identity_service.get_user(session, scope, scope.user_id)
    workspace = await identity_service.get_workspace(session, scope, scope.workspace_id)
    return {"user": user, "workspace": workspace}


async def _list_students(session: AsyncSession, scope: Scope, args: PageArgs) -> Any:
    return await identity_service.list_users(session, scope, limit=args.limit, cursor=args.cursor)


async def _list_projects(session: AsyncSession, scope: Scope, args: ListProjectsArgs) -> Any:
    return await projects_service.list_projects(
        session, scope, status=args.status, limit=args.limit, cursor=args.cursor
    )


async def _list_periods(session: AsyncSession, scope: Scope, args: ListPeriodsArgs) -> Any:
    return await reporting_service.list_periods(session, scope, through=args.through)


async def _list_obligations(session: AsyncSession, scope: Scope, args: ListObligationsArgs) -> Any:
    return await reporting_service.list_obligations(
        session, scope, args.period_id, student_id=args.student_id
    )


async def _overview(session: AsyncSession, scope: Scope, _: NoArgs) -> Any:
    as_of = now()
    return {
        "as_of": as_of,
        "next_deadline": await overview_service.next_deadline(session, scope, as_of=as_of),
        "missing_reports": await overview_service.missing_reports(session, scope, as_of=as_of),
        "missing_reports_note": overview_service.MISSING_NOTE,
        "week": await overview_service.week_reports(session, scope, as_of=as_of),
        "review_queue": await overview_service.review_queue(session, scope, as_of=as_of),
    }


async def _list_reports(session: AsyncSession, scope: Scope, args: ListReportsArgs) -> Any:
    page = await reporting_service.list_submitted_reports(
        session,
        scope,
        period_id=args.period_id,
        student_id=args.student_id,
        project_id=args.project_id,
        states=args.state,
        needs_review=args.needs_review,
        limit=args.limit,
        cursor=args.cursor,
    )
    return await assessment_service.with_assessments(session, scope, page)


async def _get_version(session: AsyncSession, scope: Scope, args: VersionArgs) -> Any:
    return await reporting_service.get_version(session, scope, args.version_id)


async def _list_versions(session: AsyncSession, scope: Scope, args: ReportArgs) -> Any:
    return await reporting_service.list_versions(session, scope, report_id=args.report_id)


async def _list_assessments(session: AsyncSession, scope: Scope, args: ListAssessmentsArgs) -> Any:
    return await assessment_service.list_assessments(
        session,
        scope,
        student_id=args.student_id,
        project_id=args.project_id,
        period_id=args.period_id,
    )


async def _assessment_evidence(session: AsyncSession, scope: Scope, args: AssessmentArgs) -> Any:
    assessment = await assessment_service.get_assessment(session, scope, args.assessment_id)
    if assessment.snapshot_id is None:
        return []
    return await assessment_service.snapshot_items(session, assessment.snapshot_id)


async def _trend(session: AsyncSession, scope: Scope, args: TrendArgs) -> Any:
    return await assessment_service.progress_series(
        session, scope, student_id=args.student_id, project_id=args.project_id
    )


async def _list_attachments(session: AsyncSession, scope: Scope, args: ListAttachmentsArgs) -> Any:
    return await artifacts_service.list_artifacts(
        session,
        scope,
        student_id=args.student_id,
        project_id=args.project_id,
        period_id=args.period_id,
    )


TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_workspaces",
        "The workspaces (labs) you belong to, with their ids and which one is the default. "
        "Pass a workspace_id to any other tool to read a different lab.",
        ListWorkspacesArgs,
        _list_workspaces,
    ),
    Tool(
        "whoami",
        "The signed-in professor and the workspace this connection reads.",
        NoArgs,
        _whoami,
    ),
    Tool(
        "list_students",
        "Everyone in the workspace, with their ids. Use it to turn a name into a student_id.",
        PageArgs,
        _list_students,
    ),
    Tool(
        "list_projects",
        "The workspace's projects, optionally by status.",
        ListProjectsArgs,
        _list_projects,
    ),
    Tool(
        "list_periods",
        "The reporting weeks, with their deadlines. Gives the period_id other tools take.",
        ListPeriodsArgs,
        _list_periods,
    ),
    Tool(
        "list_obligations",
        "Who owes a weekly report in one period, and whether it is submitted, excused or extended.",
        ListObligationsArgs,
        _list_obligations,
    ),
    Tool(
        "get_overview",
        "The professor's current week: next deadline, missing reports, who has reported, and "
        "drafts waiting for review.",
        NoArgs,
        _overview,
    ),
    Tool(
        "list_reports",
        "Submitted weekly reports (never drafts), filterable by student, project, period, state, "
        "or only those needing review. Each carries its assessment, if any.",
        ListReportsArgs,
        _list_reports,
        quotes_student_text=True,
    ),
    Tool(
        "get_report_version",
        "One submitted version of a weekly report in full: every project entry as the student "
        "wrote it.",
        VersionArgs,
        _get_version,
        quotes_student_text=True,
    ),
    Tool(
        "list_report_versions",
        "Every submitted version of one report, oldest to newest.",
        ReportArgs,
        _list_versions,
    ),
    Tool(
        "list_assessments",
        "AI-drafted progress assessments, with their review state, by student, project or period.",
        ListAssessmentsArgs,
        _list_assessments,
        quotes_student_text=True,
    ),
    Tool(
        "get_assessment_evidence",
        "The claims and quoted evidence an assessment was made from.",
        AssessmentArgs,
        _assessment_evidence,
        quotes_student_text=True,
    ),
    Tool(
        "get_trend",
        "A student's rating trajectory on one project across weeks.",
        TrendArgs,
        _trend,
    ),
    Tool(
        "list_attachments",
        "Files attached to reports: names, kinds and extraction state, not their contents.",
        ListAttachmentsArgs,
        _list_attachments,
    ),
)

BY_NAME = {tool.name: tool for tool in TOOLS}
