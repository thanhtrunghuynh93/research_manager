"""Assessment tables: rubrics, evidence snapshots, analysis runs, versions, reviews, notes.

Requirements ASSESS-01..10. An assessment version is immutable: the trend a student sees and the
history the professor relies on must not change under them, so a correction is a new version
(ASSESS-09, AC-03).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import Visibility


class ReviewState(StrEnum):
    """ASSESS-08: a draft is the professor's to approve; only an approved version is published."""

    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class RunState(StrEnum):
    """Requirements §10: job states must be distinguishable, including partial."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    DELAYED_BUDGET = "delayed_budget"
    RESTRICTED = "restricted"


class FeedbackKind(StrEnum):
    PROFESSOR_COMMENT = "professor_comment"
    STUDENT_RESPONSE = "student_response"
    CORRECTION_REQUEST = "correction_request"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


REVIEW_STATE_ENUM = _enum(ReviewState, "review_state")
RUN_STATE_ENUM = _enum(RunState, "analysis_run_state")
FEEDBACK_KIND_ENUM = _enum(FeedbackKind, "feedback_kind")
VISIBILITY_ENUM = Enum(
    Visibility, name="visibility", values_callable=lambda e: [m.value for m in e]
)


class RubricVersion(UUIDPrimaryKeyMixin, Base):
    """ASSESS-03/ASSESS-09: the weights, anchors, and rules an assessment was produced under.

    Versioned so a change appears as a labelled break in a trend rather than a silent shift in what
    a number means (AC-10).
    """

    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version"),
        UniqueConstraint("workspace_id", "id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text, default="")
    # {dimension: {weight, anchors: {0..4}}}
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # {stage: [dimensions that do not apply]} — the only source of "not applicable" (ASSESS-04).
    stage_applicability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Confidence thresholds and other rules, versioned with the rubric (ASSESS-06).
    calculation_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    effective_from: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvidenceSnapshot(UUIDPrimaryKeyMixin, Base):
    """ASSESS-01: exactly what was considered, frozen at the moment of assessment.

    Built only from evidence the student is allowed to see, because the approved assessment is
    published to them and its citations must open (QA-06).
    """

    __tablename__ = "evidence_snapshots"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        Index("ix_evidence_snapshots_subject", "student_id", "project_id", "period_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    project_id: Mapped[UUID]
    period_id: Mapped[UUID]
    window_start_utc: Mapped[datetime]
    window_end_utc: Mapped[datetime]
    integration_lag_days: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    # What was left out and why: truncated diffs, extraction failures, stale sync (ASSESS-06).
    coverage_notes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    access_epoch: Mapped[int] = mapped_column(Integer, default=0)
    built_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvidenceSnapshotItem(Base):
    """One piece of evidence in a snapshot, pinned to the version that was read."""

    __tablename__ = "evidence_snapshot_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["evidence_snapshots.workspace_id", "evidence_snapshots.id"],
            ondelete="CASCADE",
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(primary_key=True)
    evidence_ref_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source_version: Mapped[str] = mapped_column(Text, default="")
    # Repository work merged this week but authored earlier is flagged, never counted as new
    # work of the week (REPO-06).
    integration_of_earlier_work: Mapped[bool] = mapped_column(default=False, server_default="false")


class AnalysisRun(UUIDPrimaryKeyMixin, Base):
    """ASSESS-09: the inputs and per-step state of one pipeline run, so a failure is legible."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        Index("ix_analysis_runs_subject", "student_id", "project_id", "period_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    project_id: Mapped[UUID]
    period_id: Mapped[UUID]
    report_version_id: Mapped[UUID | None]
    entry_id: Mapped[UUID | None]
    snapshot_id: Mapped[UUID | None]
    rubric_version_id: Mapped[UUID | None]
    state: Mapped[RunState] = mapped_column(RUN_STATE_ENUM, default=RunState.QUEUED)
    steps: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class AssessmentVersion(UUIDPrimaryKeyMixin, Base):
    """ASSESS-01/09: one immutable assessment of one student, project, and week.

    Everything needed to reproduce it is stored: the report version, the snapshot, the rubric, and
    the model and prompt versions that produced the narrative.
    """

    __tablename__ = "assessment_versions"
    __table_args__ = (
        UniqueConstraint("student_id", "project_id", "period_id", "version_no"),
        UniqueConstraint("workspace_id", "id"),
        Index("ix_assessment_versions_subject", "student_id", "project_id", "period_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    project_id: Mapped[UUID]
    period_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(Integer)
    report_version_id: Mapped[UUID | None]
    entry_id: Mapped[UUID | None]
    baseline_id: Mapped[UUID | None]
    snapshot_id: Mapped[UUID | None]
    rubric_version_id: Mapped[UUID | None]
    analysis_run_id: Mapped[UUID | None]
    # {dimension: {rating, rationale, evidence_ref_ids}} (ASSESS-03, ASSESS-07).
    ratings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress_index: Mapped[int | None] = mapped_column(SmallInteger)
    plan_completion: Mapped[float | None] = mapped_column(Numeric(5, 2))
    coverage_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    confidence: Mapped[str] = mapped_column(Text, default="low")
    confidence_reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # accomplishments, blockers, discrepancies, limitations, next steps, discussion agenda.
    narrative: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AssessmentReview(UUIDPrimaryKeyMixin, Base):
    """ASSESS-08: the professor's decision on one version, and the reason for any override.

    The original model output stays in `assessment_versions`; an override is recorded here beside
    it rather than replacing it.
    """

    __tablename__ = "assessment_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "assessment_version_id"],
            ["assessment_versions.workspace_id", "assessment_versions.id"],
            ondelete="CASCADE",
        ),
        # At most one approved review per version: what a student sees is unambiguous.
        Index(
            "uq_one_approved",
            "assessment_version_id",
            unique=True,
            postgresql_where=text("state = 'approved'"),
        ),
        Index("ix_assessment_reviews_state", "state"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    assessment_version_id: Mapped[UUID]
    state: Mapped[ReviewState] = mapped_column(REVIEW_STATE_ENUM, default=ReviewState.DRAFT)
    reviewer_id: Mapped[UUID | None]
    override: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Feedback(UUIDPrimaryKeyMixin, Base):
    """Comments on an assessment or a report, including a student's correction request."""

    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_subject", "subject_table", "subject_id"),
        Index("ix_feedback_recipient", "recipient_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    subject_table: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID]
    recipient_id: Mapped[UUID | None]
    author_id: Mapped[UUID]
    kind: Mapped[FeedbackKind] = mapped_column(FEEDBACK_KIND_ENUM)
    visibility: Mapped[Visibility] = mapped_column(VISIBILITY_ENUM)
    body: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    responds_to_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SupervisionNote(UUIDPrimaryKeyMixin, Base):
    """QA-06: private to the professors. Never indexed, never in a snapshot, never in an answer
    a student can read. Kept in its own table so that is structural rather than a filter.

    "Private" means not a student, not not-another-professor: co-supervisors share the workspace's
    notes (ADR 0011). `author_id` is what lets a reader tell whose note they are looking at."""

    __tablename__ = "supervision_notes"
    __table_args__ = (Index("ix_supervision_notes_subject", "student_id", "project_id"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    author_id: Mapped[UUID]
    student_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    period_id: Mapped[UUID | None]
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
