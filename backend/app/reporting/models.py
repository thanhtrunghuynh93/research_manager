"""Reporting tables: calendar, periods, obligations, reports, versions, entries.

Requirements REP-01..06. Submitted versions and their entries are immutable at the database level
(architecture §5.3): a record the professor has already assessed cannot be edited out from under
the assessment that cites it.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class ObligationState(StrEnum):
    REQUIRED = "required"
    EXCUSED = "excused"


class ReportState(StrEnum):
    """REP-05: draft, submitted, revision requested, resubmitted, reviewed."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVISION_REQUESTED = "revision_requested"
    RESUBMITTED = "resubmitted"
    REVIEWED = "reviewed"


class TimingStatus(StrEnum):
    """REP-05: timing is recorded separately from the workflow state."""

    ON_TIME = "on_time"
    LATE = "late"
    EXCUSED = "excused"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


OBLIGATION_STATE_ENUM = _enum(ObligationState, "obligation_state")
REPORT_STATE_ENUM = _enum(ReportState, "report_state")
TIMING_STATUS_ENUM = _enum(TimingStatus, "timing_status")


class CalendarConfig(UUIDPrimaryKeyMixin, Base):
    """REP-01: a versioned calendar. Changing it applies to future periods only."""

    __tablename__ = "calendar_configs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version"),
        UniqueConstraint("workspace_id", "id"),
        Index("ix_calendar_configs_workspace_id_effective_from", "workspace_id", "effective_from"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(Text)
    meeting_weekday: Mapped[int] = mapped_column(SmallInteger)  # Monday = 0 … Sunday = 6
    week_start_weekday: Mapped[int] = mapped_column(SmallInteger)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    effective_from: Mapped[date]
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReportingPeriod(UUIDPrimaryKeyMixin, Base):
    """One reporting week. Timestamps are UTC; the local dates and calendar version travel with it.

    `deadline_utc` is 23:59 local on the day before `meeting_date`, and the meeting is the first
    configured meeting weekday after the period ends — the meeting discusses the week just reported
    (REP-01).
    """

    __tablename__ = "reporting_periods"
    __table_args__ = (
        UniqueConstraint("workspace_id", "local_start"),
        UniqueConstraint("workspace_id", "id"),
        Index("ix_reporting_periods_workspace_id_deadline_utc", "workspace_id", "deadline_utc"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    calendar_config_id: Mapped[UUID]
    local_start: Mapped[date]
    local_end: Mapped[date]
    start_utc: Mapped[datetime]
    end_utc: Mapped[datetime]
    meeting_date: Mapped[date]
    deadline_utc: Mapped[datetime]
    reminder_due_utc: Mapped[datetime]
    reminder_dispatched_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReportingObligation(UUIDPrimaryKeyMixin, Base):
    """REP-01/REP-06: what one membership owes for one period, and any exception to it."""

    __tablename__ = "reporting_obligations"
    __table_args__ = (
        UniqueConstraint("membership_id", "period_id"),
        ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "membership_id"],
            ["project_memberships.workspace_id", "project_memberships.id"],
            ondelete="CASCADE",
        ),
        Index("ix_reporting_obligations_period_id_state", "period_id", "state"),
        Index("ix_reporting_obligations_student_id", "student_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    membership_id: Mapped[UUID]
    period_id: Mapped[UUID]
    # Denormalised from the membership so the missed-deadline job and the overview can answer
    # "who owes what this week" without joining through projects (REP-08).
    student_id: Mapped[UUID]
    project_id: Mapped[UUID]
    state: Mapped[ObligationState] = mapped_column(
        OBLIGATION_STATE_ENUM, default=ObligationState.REQUIRED
    )
    excuse_reason: Mapped[str | None] = mapped_column(Text)
    extension_until_utc: Mapped[datetime | None]
    extension_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WeeklyReport(UUIDPrimaryKeyMixin, Base):
    """REP-02: one report per student per period, carrying the live draft and the version history.

    `first_submitted_at` is written once and never updated: a revision request, a reminder, or a
    later version must not move the moment the student first handed the work in (REP-07, AC-13).
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("student_id", "period_id"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            ondelete="CASCADE",
        ),
        Index("ix_weekly_reports_period_id_workflow_state", "period_id", "workflow_state"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    period_id: Mapped[UUID]
    workflow_state: Mapped[ReportState] = mapped_column(
        REPORT_STATE_ENUM, default=ReportState.DRAFT
    )
    first_submitted_at: Mapped[datetime | None]
    current_version_id: Mapped[UUID | None]
    draft_content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    draft_saved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReportVersion(UUIDPrimaryKeyMixin, Base):
    """REP-05: an immutable submission. Revisions add versions; they never replace history."""

    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("report_id", "version_no"),
        UniqueConstraint("report_id", "idempotency_key"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["weekly_reports.workspace_id", "weekly_reports.id"],
            ondelete="CASCADE",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    report_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[UUID]
    submitted_at: Mapped[datetime]
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    timing_status: Mapped[TimingStatus] = mapped_column(TIMING_STATUS_ENUM)


class ProjectReportEntry(UUIDPrimaryKeyMixin, Base):
    """REP-03: one project's section of the weekly package. Immutable, like its version.

    `content_hash` covers the research content and excludes self-reported hours, so re-stating the
    same work with an hours figure added is not a change. `content_changed_in_version_id` names the
    version in which this entry's content last moved, which is what decides whether a new
    assessment is created (REP-05, ASSESS-09, AC-17).
    """

    __tablename__ = "project_report_entries"
    __table_args__ = (
        UniqueConstraint("report_version_id", "project_id"),
        ForeignKeyConstraint(
            ["workspace_id", "report_version_id"],
            ["report_versions.workspace_id", "report_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index("ix_project_report_entries_project_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    report_version_id: Mapped[UUID]
    project_id: Mapped[UUID]
    stage: Mapped[str] = mapped_column(Text)
    planned_work_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    work_performed: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[str] = mapped_column(Text, default="")
    experiments: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    deviations: Mapped[str] = mapped_column(Text, default="")
    next_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    questions: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # Optional and self-reported; never treated as verified productivity (REP-03).
    hours: Mapped[float | None] = mapped_column(Numeric(6, 2))
    content_hash: Mapped[bytes] = mapped_column(LargeBinary)
    content_changed_in_version_id: Mapped[UUID]


class RevisionRequest(UUIDPrimaryKeyMixin, Base):
    """REP-05: a revision request targets one project entry, not the whole package."""

    __tablename__ = "revision_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["weekly_reports.workspace_id", "weekly_reports.id"],
            ondelete="CASCADE",
        ),
        Index("ix_revision_requests_report_id", "report_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    report_id: Mapped[UUID]
    report_version_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[UUID]
    resolved_in_version_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ArtifactKind(StrEnum):
    """Where the bytes came from. A link is fetched; an upload is handed to us (REP-04)."""

    UPLOAD = "upload"
    LINK = "link"


class ExtractionState(StrEnum):
    """REP-04: an extraction failure is recorded rather than left as empty text."""

    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


ARTIFACT_KIND_ENUM = _enum(ArtifactKind, "artifact_kind")
EXTRACTION_STATE_ENUM = _enum(ExtractionState, "extraction_state")


class Artifact(UUIDPrimaryKeyMixin, Base):
    """One piece of attached evidence, owned by the student who attached it.

    The artifact is the identity; the bytes live in its versions, so replacing a figure keeps the
    citation stable and keeps the version that an assessment already read (REP-04, ASSESS-09).
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        Index("ix_artifacts_owner", "owner_student_id", "created_at"),
        Index("ix_artifacts_project", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    owner_student_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    # The entry it supports, when it was attached to one. Null while it is still a draft's file.
    entry_id: Mapped[UUID | None]
    period_id: Mapped[UUID | None]
    kind: Mapped[ArtifactKind] = mapped_column(ARTIFACT_KIND_ENUM, default=ArtifactKind.UPLOAD)
    filename: Mapped[str] = mapped_column(Text)
    # What the student says this file shows. Their claim, recorded as theirs (REPO-08).
    supported_claim: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ArtifactVersion(UUIDPrimaryKeyMixin, Base):
    """The bytes, their checksum, and what reading them produced (architecture §5.6)."""

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version_no"),
        ForeignKeyConstraint(
            ["workspace_id", "artifact_id"],
            ["artifacts.workspace_id", "artifacts.id"],
            ondelete="CASCADE",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    artifact_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(Text, default="application/octet-stream")
    storage_key: Mapped[str] = mapped_column(Text)
    extraction_state: Mapped[ExtractionState] = mapped_column(
        EXTRACTION_STATE_ENUM, default=ExtractionState.PENDING
    )
    extracted_text_key: Mapped[str | None] = mapped_column(Text)
    # What was omitted and why, so the coverage note can say it (ASSESS-06).
    extraction_note: Mapped[str] = mapped_column(Text, default="")
    truncated: Mapped[bool] = mapped_column(default=False, server_default="false")
    # False until the upload is confirmed: a presigned URL is a grant, not a fact.
    uploaded: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
