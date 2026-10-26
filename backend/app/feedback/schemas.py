"""What the feedback service returns: plain models, never an ORM row (repo_layout §3.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FeedbackStatus = Literal["draft", "published"]


class AttachmentOut(BaseModel):
    attachment_id: UUID
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    # A short-lived private link, present only when the caller asked for links. Never a permanent
    # public URL: it stops working after `download_expires_in` seconds.
    download_url: str | None = None
    download_expires_in: int | None = None


class ReportRefOut(BaseModel):
    report_id: UUID
    period_id: UUID
    local_start: str
    local_end: str


class FeedbackOut(BaseModel):
    feedback_id: UUID
    workspace_id: UUID
    student_id: UUID
    project_id: UUID
    report_ids: list[UUID]
    reports: list[ReportRefOut]
    title: str
    body_markdown: str
    # The revision shown. For a professor it is the newest (the draft) unless they asked for an
    # older one; for a student it is always the published one.
    version: int
    status: FeedbackStatus
    published_version: int | None
    has_unpublished_changes: bool
    attachments: list[AttachmentOut]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    view_url: str


class FeedbackSummary(BaseModel):
    """A row of a list: no body, no files — `get_feedback` has those."""

    feedback_id: UUID
    student_id: UUID
    project_id: UUID
    report_ids: list[UUID]
    title: str
    version: int
    status: FeedbackStatus
    published_version: int | None
    has_unpublished_changes: bool
    attachment_count: int
    updated_at: datetime
    published_at: datetime | None
    view_url: str


class RevisionOut(BaseModel):
    version: int
    title: str
    report_ids: list[UUID]
    attachment_ids: list[UUID]
    created_by: UUID
    created_at: datetime
    published_at: datetime | None


class UploadGrantOut(BaseModel):
    attachment_id: UUID
    filename: str
    state: Literal["pending"] = "pending"
    upload_url: str
    upload_method: Literal["PUT"] = "PUT"
    upload_headers: dict[str, str]
    expires_in: int
    next_step: str = Field(
        default="PUT the file's bytes to upload_url with upload_headers, then confirm the "
        "upload with this attachment_id. The file is not attached until it is confirmed."
    )
