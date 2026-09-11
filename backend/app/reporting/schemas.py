"""Request and response models for the reporting API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-exported for the API layer, which must not import ORM modules directly.
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


class ExcuseIn(BaseModel):
    reason: str = Field(min_length=1)


class ExtensionIn(BaseModel):
    until: datetime
    reason: str = Field(min_length=1)


class EntryIn(BaseModel):
    """REP-03: one project's section of the weekly package."""

    project_id: UUID
    stage: str
    milestone_ids: list[UUID] = Field(default_factory=list)
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
    milestone_ids: list[UUID]
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


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_id: UUID
    version_no: int
    author_id: UUID
    submitted_at: datetime
    timing_status: TimingStatus
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
