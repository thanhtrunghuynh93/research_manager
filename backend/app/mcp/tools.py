"""The tools a connector may call (ADR 0025, ADR 0026).

Almost all are read-only. The feedback tools write, need the `rms:feedback` grant on the token, and
say so in their annotations; they only ever write drafts and files until `publish_feedback`.

Each tool is a thin call into a service function with the professor's Scope, so what it returns is
exactly what the same professor sees in the app: the visibility predicates do the filtering, and
nothing here widens them. A tool takes a pydantic model for its arguments, which gives the client a
JSON Schema and validates the call in one place.

Tools that return text students wrote say so (`quotes_student_text`): the server prefixes their
result with a notice that the text is quoted data, since it ends up in a model's context.
"""

from __future__ import annotations

import base64
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
from app.core.errors import ValidationError
from app.feedback import service as feedback_service
from app.feedback.schemas import FeedbackStatus
from app.identity import service as identity_service
from app.oauth.service import SCOPE_FEEDBACK
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


class CreateFeedbackArgs(WorkspaceArgs):
    student_id: UUID
    project_id: UUID
    report_ids: list[UUID] = Field(
        min_length=1,
        max_length=feedback_service.MAX_REPORTS,
        description="The student's submitted weekly reports this feedback is about; each must "
        "have a section on the project. list_reports gives the ids.",
    )
    title: str = Field(min_length=1, max_length=feedback_service.MAX_TITLE)
    body_markdown: str = Field(min_length=1, max_length=feedback_service.MAX_BODY)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Send the same key when retrying so the draft is not created twice.",
    )


class FeedbackIdArgs(WorkspaceArgs):
    feedback_id: UUID


class GetFeedbackArgs(FeedbackIdArgs):
    version: int | None = Field(
        default=None, ge=1, description="An earlier version; omit for the newest draft."
    )
    include_download_urls: bool = Field(
        default=True, description="Add a short-lived private download link to each file."
    )


class ListFeedbackArgs(PageArgs):
    student_id: UUID | None = None
    project_id: UUID | None = None
    report_id: UUID | None = None
    status: FeedbackStatus | None = None


class UpdateFeedbackArgs(FeedbackIdArgs):
    expected_version: int = Field(
        ge=1, description="The version you read. A newer one means someone changed it: re-read."
    )
    title: str | None = Field(default=None, min_length=1, max_length=feedback_service.MAX_TITLE)
    body_markdown: str | None = Field(
        default=None, min_length=1, max_length=feedback_service.MAX_BODY
    )
    report_ids: list[UUID] | None = Field(
        default=None, min_length=1, max_length=feedback_service.MAX_REPORTS
    )
    remove_attachment_ids: list[UUID] = Field(default_factory=list)


class UploadAttachmentArgs(FeedbackIdArgs):
    """Two ways in, so a connector that cannot make an HTTP PUT can still attach a small file."""

    attachment_id: UUID | None = Field(
        default=None,
        description="Step 2: the attachment_id from step 1, after the bytes were PUT to its "
        "upload_url. Verifies the file and attaches it.",
    )
    filename: str | None = Field(
        default=None,
        max_length=feedback_service.MAX_FILENAME,
        description="Step 1 or inline: the file's name. Allowed: .html .pdf .docx .txt .md.",
    )
    byte_size: int | None = Field(default=None, gt=0, description="Step 1: size in bytes.")
    sha256: str | None = Field(
        default=None, description="Step 1: the file's SHA-256, 64 lowercase hex characters."
    )
    content_base64: str | None = Field(
        default=None,
        description="Inline: the file itself, base64, for a small file (default limit 2 MB). "
        "Attaches in one call.",
    )
    expected_version: int | None = Field(
        default=None, ge=1, description="Optional: refuse if the feedback has moved past this."
    )


class PublishFeedbackArgs(FeedbackIdArgs):
    expected_version: int = Field(
        ge=1, description="The version you reviewed. Publishing refuses if it has changed."
    )
    notify_student: bool = Field(
        default=False, description="Not available yet: true is refused. Nobody is notified."
    )
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    quotes_student_text: bool = False
    # None for a read; otherwise the OAuth scope the token must have been granted.
    requires_scope: str | None = None
    # A write that repeating cannot make worse (same key, same result). Reads are idempotent too.
    idempotent: bool = True
    # Replaces or discards something that existed. Nothing here does today: edits add a revision.
    destructive: bool = False

    @property
    def read_only(self) -> bool:
        return self.requires_scope is None


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


async def _create_feedback(session: AsyncSession, scope: Scope, args: CreateFeedbackArgs) -> Any:
    return await feedback_service.create_feedback(
        session,
        scope,
        student_id=args.student_id,
        project_id=args.project_id,
        report_ids=args.report_ids,
        title=args.title,
        body_markdown=args.body_markdown,
        idempotency_key=args.idempotency_key,
    )


async def _get_feedback(session: AsyncSession, scope: Scope, args: GetFeedbackArgs) -> Any:
    return await feedback_service.get_feedback(
        session,
        scope,
        args.feedback_id,
        version=args.version,
        with_download_urls=args.include_download_urls,
    )


async def _list_feedback(session: AsyncSession, scope: Scope, args: ListFeedbackArgs) -> Any:
    return await feedback_service.list_feedback(
        session,
        scope,
        student_id=args.student_id,
        project_id=args.project_id,
        report_id=args.report_id,
        status=args.status,
        limit=args.limit,
        cursor=args.cursor,
    )


async def _update_feedback(session: AsyncSession, scope: Scope, args: UpdateFeedbackArgs) -> Any:
    return await feedback_service.update_feedback(
        session,
        scope,
        args.feedback_id,
        expected_version=args.expected_version,
        title=args.title,
        body_markdown=args.body_markdown,
        report_ids=args.report_ids,
        remove_attachment_ids=args.remove_attachment_ids,
    )


async def _publish_feedback(session: AsyncSession, scope: Scope, args: PublishFeedbackArgs) -> Any:
    return await feedback_service.publish_feedback(
        session,
        scope,
        args.feedback_id,
        expected_version=args.expected_version,
        notify_student=args.notify_student,
        idempotency_key=args.idempotency_key,
    )


async def _upload_attachment(
    session: AsyncSession, scope: Scope, args: UploadAttachmentArgs
) -> Any:
    if args.attachment_id is not None:
        if args.content_base64 is not None or args.sha256 is not None:
            raise ValidationError("to confirm an upload, give only feedback_id and attachment_id")
        return await feedback_service.confirm_attachment(
            session,
            scope,
            args.feedback_id,
            args.attachment_id,
            expected_version=args.expected_version,
        )
    if args.filename is None:
        raise ValidationError("give a filename, or an attachment_id to confirm an upload")
    if args.content_base64 is not None:
        try:
            content = base64.b64decode(args.content_base64, validate=True)
        except ValueError:
            raise ValidationError("content_base64 is not valid base64") from None
        return await feedback_service.upload_attachment_inline(
            session,
            scope,
            args.feedback_id,
            filename=args.filename,
            content=content,
            expected_version=args.expected_version,
        )
    if args.byte_size is None or args.sha256 is None:
        raise ValidationError("step 1 needs filename, byte_size and sha256")
    return await feedback_service.request_attachment_upload(
        session,
        scope,
        args.feedback_id,
        filename=args.filename,
        byte_size=args.byte_size,
        sha256=args.sha256,
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
    Tool(
        "list_feedback",
        "Feedback you wrote for students, drafts included, by student, project, report or "
        "status. No bodies: get_feedback has those.",
        ListFeedbackArgs,
        _list_feedback,
    ),
    Tool(
        "get_feedback",
        "One feedback in full: text, status, version, the reports it covers, and its files with "
        "their SHA-256 and a short-lived download link. Review a draft here before publishing.",
        GetFeedbackArgs,
        _get_feedback,
    ),
    Tool(
        "create_feedback",
        "Save a DRAFT feedback for one student and project, about one or more of their weekly "
        "reports. The student cannot see it and is not told until publish_feedback.",
        CreateFeedbackArgs,
        _create_feedback,
        requires_scope=SCOPE_FEEDBACK,
        idempotent=False,  # only when the caller sends an idempotency_key
    ),
    Tool(
        "upload_feedback_attachment",
        "Attach a .html, .pdf, .docx, .txt or .md file (max 20 MB) to a feedback draft. Either "
        "send a small file inline (filename + content_base64), or in two steps: filename + "
        "byte_size + sha256 returns an upload_url to PUT the bytes to, then call again with the "
        "attachment_id to verify and attach it. Nothing is attached until verification passes. "
        "Does not publish or notify.",
        UploadAttachmentArgs,
        _upload_attachment,
        requires_scope=SCOPE_FEEDBACK,
        idempotent=False,
    ),
    Tool(
        "update_feedback",
        "Change a feedback's title, text, reports, or remove files, giving the version you read. "
        "Creates a new version and keeps the old ones. If it was published, students keep seeing "
        "the published version until you publish again.",
        UpdateFeedbackArgs,
        _update_feedback,
        requires_scope=SCOPE_FEEDBACK,
        idempotent=False,
    ),
    Tool(
        "publish_feedback",
        "Make the version you reviewed visible to the student (only that student). Refuses if the "
        "draft changed since expected_version. notify_student is not available yet.",
        PublishFeedbackArgs,
        _publish_feedback,
        requires_scope=SCOPE_FEEDBACK,
    ),
)

BY_NAME = {tool.name: tool for tool in TOOLS}
