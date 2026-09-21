"""Request and response models for the reporting API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# Re-exported for the API layer, which must not import ORM modules directly.
from app.reporting.models import ArtifactKind as ArtifactKind
from app.reporting.models import ExtractionState as ExtractionState
from app.reporting.models import ObligationState as ObligationState
from app.reporting.models import ReportState as ReportState
from app.reporting.models import TimingStatus as TimingStatus


class CalendarConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    timezone: str
    meeting_weekday: int
    week_start_weekday: int
    grace_minutes: int
    effective_from: date


class CalendarConfigIn(BaseModel):
    timezone: str = "Asia/Ho_Chi_Minh"
    meeting_weekday: int = Field(default=0, ge=0, le=6)
    week_start_weekday: int = Field(default=0, ge=0, le=6)
    grace_minutes: int = Field(default=0, ge=0, le=1440)
    effective_from: date


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # A professor's reads span every workspace they belong to (ADR 0016), and each workspace keeps
    # its own calendar — so "this week" is one period per workspace, not one period. Without this
    # the weeks came back in a single list with nothing to group them by.
    workspace_id: UUID
    local_start: date
    local_end: date
    start_utc: datetime
    end_utc: datetime
    meeting_date: date
    deadline_utc: datetime
    reminder_due_utc: datetime


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_id: UUID
    membership_id: UUID
    student_id: UUID
    project_id: UUID
    state: ObligationState
    excuse_reason: str | None = None
    extension_until_utc: datetime | None = None
    # REP-08: `state` says whether this project has to be in the package, never whether it is.
    # Without this the student's screen had no way to tell a finished week from an untouched one,
    # and rendered every obligation as outstanding however many times it had been submitted.
    submitted: bool = False


def _require_non_blank(value: str) -> str:
    """Trimmed, and refused when nothing is left.

    `min_length=1` counts whitespace, so a reason of three spaces satisfied it — and these are
    reasons a professor gives for excusing or extending someone's obligation, which is exactly the
    kind of record that has to say something when it is read back.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


NonBlank = Annotated[str, AfterValidator(_require_non_blank)]


class ExcuseIn(BaseModel):
    reason: NonBlank


class ExtensionIn(BaseModel):
    until: datetime
    reason: NonBlank


class EntryIn(BaseModel):
    """REP-03: one project's section of the weekly package."""

    project_id: UUID
    stage: str
    planned_work_ref: dict[str, Any] = Field(default_factory=dict)
    work_performed: str = ""
    results: str = ""
    experiments: list[Any] = Field(default_factory=list)
    deviations: str = ""
    next_plan: dict[str, Any] = Field(default_factory=dict)
    questions: str = ""
    evidence_refs: list[Any] = Field(default_factory=list)
    hours: Decimal | None = Field(default=None, ge=0, le=168)


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_version_id: UUID
    project_id: UUID
    stage: str
    planned_work_ref: dict[str, Any]
    work_performed: str
    results: str
    experiments: list[Any]
    deviations: str
    next_plan: dict[str, Any]
    questions: str
    evidence_refs: list[Any]
    hours: Decimal | None = None
    content_changed_in_version_id: UUID


class VersionSummaryOut(BaseModel):
    """One submitted version, without its entries.

    A list of *full* versions is an N+1 and a large payload, and the screen that lists them only
    needs enough to choose one — so the entries stay behind `GET /report-versions/{id}`, which is
    what selecting a version calls.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_id: UUID
    version_no: int
    author_id: UUID
    submitted_at: datetime
    timing_status: TimingStatus


class VersionOut(VersionSummaryOut):
    # Subclassed rather than duplicated so the wire shape of `VersionOut` is unchanged: every
    # existing caller and the generated client see exactly what they saw before.
    entries: list[EntryOut] = Field(default_factory=list)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    period_id: UUID
    workflow_state: ReportState
    first_submitted_at: datetime | None = None
    current_version_id: UUID | None = None
    draft_content: dict[str, Any]
    draft_saved_at: datetime | None = None


class DraftIn(BaseModel):
    content: dict[str, Any] = Field(default_factory=dict)


class SubmitIn(BaseModel):
    entries: list[EntryIn]


class RevisionRequestIn(BaseModel):
    project_id: UUID | None = None
    reason: str = Field(min_length=1)


class RevisionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_id: UUID
    report_version_id: UUID
    project_id: UUID | None = None
    reason: str
    requested_by: UUID
    resolved_in_version_id: UUID | None = None
    created_at: datetime
