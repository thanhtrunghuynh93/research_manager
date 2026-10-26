"""Feedback tables (ADR 0026).

A `Feedback` is the identity: one professor's response to one student's work on one project, tied
to the weekly reports it is about. What it says lives in `FeedbackRevision` rows, one per change,
so the history is kept and the revision a student sees is a row that no later edit can touch.
`Feedback.version` is the newest revision (the draft) and `published_version` is the one students
read; they differ while a published feedback has unpublished edits.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class AttachmentState(StrEnum):
    """`pending` from the grant until the bytes have been checked; only then `ready`."""

    PENDING = "pending"
    READY = "ready"


class Feedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "feedbacks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index("ix_feedbacks_workspace_id_student_id", "workspace_id", "student_id"),
        Index("ix_feedbacks_project_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    project_id: Mapped[UUID]
    # Taken from the caller's Scope, never from the request: whoever opened it.
    author_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class FeedbackRevision(UUIDPrimaryKeyMixin, Base):
    """One state of a feedback. Content never changes after the row is written."""

    __tablename__ = "feedback_revisions"
    __table_args__ = (
        UniqueConstraint("feedback_id", "version_no"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "feedback_id"],
            ["feedbacks.workspace_id", "feedbacks.id"],
            ondelete="CASCADE",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    feedback_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    # Checked on write to be this student's reports with an entry for this project. An array
    # rather than a link table: it is read and written whole, with the revision.
    report_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    author_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]
    published_by: Mapped[UUID | None]


class FeedbackAttachment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "feedback_attachments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("state IN ('pending', 'ready')", name="state"),
        ForeignKeyConstraint(
            ["workspace_id", "feedback_id"],
            ["feedbacks.workspace_id", "feedbacks.id"],
            ondelete="CASCADE",
        ),
        Index("ix_feedback_attachments_feedback_id", "feedback_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    feedback_id: Mapped[UUID]
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default=AttachmentState.PENDING.value)
    created_by: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None]


class FeedbackRevisionAttachment(Base):
    """Which files a revision carries, so a published revision's file list is frozen with it."""

    __tablename__ = "feedback_revision_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "revision_id"],
            ["feedback_revisions.workspace_id", "feedback_revisions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "attachment_id"],
            ["feedback_attachments.workspace_id", "feedback_attachments.id"],
            ondelete="CASCADE",
        ),
        Index("ix_feedback_revision_attachments_attachment_id", "attachment_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    revision_id: Mapped[UUID] = mapped_column(primary_key=True)
    attachment_id: Mapped[UUID] = mapped_column(primary_key=True)


class FeedbackIdempotency(UUIDPrimaryKeyMixin, Base):
    """A retry-safe key: the first call under it does the work, later calls report that result."""

    __tablename__ = "feedback_idempotency"
    __table_args__ = (UniqueConstraint("workspace_id", "actor_id", "operation", "key"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    # What the first call asked for, so the same key on a different request is refused rather than
    # answered with the wrong feedback.
    request_hash: Mapped[str] = mapped_column(Text)
    feedback_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
