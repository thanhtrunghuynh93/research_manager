"""Feedback, as the people it is for read it (ADR 0026).

A student gets the feedback a professor published to them and nothing else: the visibility
predicates decide, so a draft, someone else's feedback and another workspace's all answer 404.
A professor reads every feedback in the workspace they are in, drafts included. Writing is done
through the MCP tools, not here. Files are never streamed by this process: a download is a
time-limited link, issued only after the same permission check.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import ScopeDep, SessionDep
from app.core.pagination import Page
from app.feedback import service
from app.feedback.schemas import FeedbackOut, FeedbackStatus, FeedbackSummary

router = APIRouter(prefix="/feedback", tags=["feedback"])


class DownloadOut(BaseModel):
    url: str
    filename: str
    expires_in: int


@router.get("", summary="Feedback the caller may read, newest first")
async def list_feedback(
    scope: ScopeDep,
    session: SessionDep,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    report_id: UUID | None = None,
    status: FeedbackStatus | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[FeedbackSummary]:
    return await service.list_feedback(
        session,
        scope,
        student_id=student_id,
        project_id=project_id,
        report_id=report_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.get("/attachments/{attachment_id}/download", summary="A time-limited link to the file")
async def download(attachment_id: UUID, scope: ScopeDep, session: SessionDep) -> DownloadOut:
    attachment, link = await service.attachment_download(session, scope, attachment_id)
    return DownloadOut(url=link.url, filename=attachment.filename, expires_in=link.expires_in)


@router.get("/{feedback_id}", summary="One feedback; a student sees the published version")
async def get_feedback(feedback_id: UUID, scope: ScopeDep, session: SessionDep) -> FeedbackOut:
    return await service.get_feedback(session, scope, feedback_id)
