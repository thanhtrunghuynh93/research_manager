"""Request and response models for the assessment API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# Re-exported for the API layer, which must not import ORM modules directly.
from app.assessment.models import FeedbackKind as FeedbackKind
from app.assessment.models import ReviewState as ReviewState
from app.assessment.models import RunState as RunState
from app.core.types import Visibility


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    project_id: UUID
    period_id: UUID
    window_start_utc: datetime
    window_end_utc: datetime
    integration_lag_days: int
    item_count: int
    coverage_notes: dict[str, Any]
    access_epoch: int
    built_at: datetime


class SnapshotItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_ref_id: UUID
    text: str
    locator: str
    visibility: Visibility
    source_version: str
    integration_of_earlier_work: bool


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    project_id: UUID
    period_id: UUID
    version_no: int
    report_version_id: UUID | None = None
    entry_id: UUID | None = None
    baseline_id: UUID | None = None
    snapshot_id: UUID | None = None
    rubric_version_id: UUID | None = None
    analysis_run_id: UUID | None = None
    ratings: dict[str, Any]
    progress_index: int | None = None
    plan_completion: Decimal | None = None
    coverage_pct: Decimal
    confidence: str
    confidence_reasons: list[Any]
    narrative: dict[str, Any]
    reason: str = ""
    model_name: str | None = None
    prompt_versions: dict[str, Any]
    created_at: datetime

    # What stands after any professor override, beside the model's untouched output.
    effective_ratings: dict[str, Any] = Field(default_factory=dict)
    review_state: ReviewState | None = None
    published_at: datetime | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assessment_version_id: UUID
    state: ReviewState
    reviewer_id: UUID | None = None
    override: dict[str, Any] | None = None
    rationale: str | None = None
    published_at: datetime | None = None
    created_at: datetime


class ApproveIn(BaseModel):
    override: dict[str, Any] | None = None
    rationale: str | None = None


def _require_non_blank(value: str) -> str:
    """Trimmed, and refused when nothing is left."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


# A body that is only whitespace is an empty body. `min_length=1` counted the spaces, so three of
# them were accepted and filed against an assessment — a correction request the professor received
# and could read nothing in, and which the student cannot withdraw.
NonBlank = Annotated[str, AfterValidator(_require_non_blank)]


class CorrectionIn(BaseModel):
    body: NonBlank
    evidence: list[Any] = Field(default_factory=list)


class SupervisionNoteIn(BaseModel):
    body: NonBlank
    student_id: UUID | None = None
    project_id: UUID | None = None
    period_id: UUID | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_table: str
    subject_id: UUID
    author_id: UUID
    kind: FeedbackKind
    visibility: Visibility
    body: str
    evidence_refs: list[Any]
    created_at: datetime


class TrendPoint(BaseModel):
    """ASSESS-10: one point in a trajectory, labelled with the rubric behind it (AC-10)."""

    period_id: UUID
    assessment_id: UUID
    progress_index: int | None = None
    plan_completion: Decimal | None = None
    confidence: str
    rubric_version_id: UUID | None = None
    created_at: datetime
