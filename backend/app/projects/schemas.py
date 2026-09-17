"""Request and response models for the projects API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-exported for the API layer, which must not import ORM modules directly.
from app.projects.models import BaselineState as BaselineState
from app.projects.models import MembershipOrigin as MembershipOrigin
from app.projects.models import MilestoneStatus as MilestoneStatus
from app.projects.models import ProjectStatus as ProjectStatus
from app.projects.models import ResearchStage as ResearchStage
from app.projects.models import TaskStatus as TaskStatus


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    title: str
    description: str
    research_questions: list[str]
    intended_contributions: list[str]
    stage: ResearchStage
    status: ProjectStatus
    start_on: date | None = None
    target_on: date | None = None
    venue_target: str | None = None
    shared_resources: dict[str, Any]
    ai_restricted: bool
    open_to_join: bool
    # AUTH-07: the client decides who may edit from this, so it has to travel with the record.
    created_by: UUID | None = None
    created_at: datetime


class JoinableProjectOut(BaseModel):
    """What a student may see about a project *before* joining it (PROJ-07).

    Deliberately not `ProjectOut`. Research questions, intended contributions, the venue target and
    the shared resources are the substance of an unpublished research programme, and someone who
    has not joined has no claim on them. This is the directory entry, not the record.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    stage: ResearchStage
    status: ProjectStatus
    member_count: int = 0


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    stage: ResearchStage
    research_questions: list[str] = Field(default_factory=list)
    intended_contributions: list[str] = Field(default_factory=list)
    start_on: date | None = None
    target_on: date | None = None
    venue_target: str | None = None
    shared_resources: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    stage: ResearchStage | None = None
    status: ProjectStatus | None = None
    research_questions: list[str] | None = None
    intended_contributions: list[str] | None = None
    start_on: date | None = None
    target_on: date | None = None
    venue_target: str | None = None
    shared_resources: dict[str, Any] | None = None
    ai_restricted: bool | None = None
    open_to_join: bool | None = None


class JoinIn(BaseModel):
    responsibility: str = ""


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    student_id: UUID
    # PROJ-02: members see who else works on the project. The name travels with the membership
    # because that is the read the disclosure is authorised by — `user_visible_to` restricts a
    # student to their own account, and asking it for a co-member fails closed.
    student_name: str = ""
    responsibility: str
    origin: MembershipOrigin
    joined_on: date
    left_on: date | None = None
    planned_allocation: Decimal | None = None
    created_at: datetime


class MembershipIn(BaseModel):
    student_id: UUID
    responsibility: str = ""
    joined_on: date | None = None
    planned_allocation: Decimal | None = Field(default=None, ge=0, le=100)


class MembershipEndIn(BaseModel):
    left_on: date | None = None


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str
    owner_id: UUID | None = None
    contributor_ids: list[UUID]
    target_on: date | None = None
    status: MilestoneStatus
    success_criteria: str
    weight: Decimal
    accepted_completion: Decimal
    revision_no: int
    created_at: datetime


class MilestoneIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    owner_id: UUID | None = None
    contributor_ids: list[UUID] = Field(default_factory=list)
    target_on: date | None = None
    success_criteria: str = ""
    weight: Decimal = Field(default=Decimal(1), ge=0)


class MilestonePatch(BaseModel):
    """A change that alters scope, weight, or criteria keeps the previous revision (PROJ-06)."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    owner_id: UUID | None = None
    contributor_ids: list[UUID] | None = None
    target_on: date | None = None
    status: MilestoneStatus | None = None
    success_criteria: str | None = None
    weight: Decimal | None = Field(default=None, ge=0)
    accepted_completion: Decimal | None = Field(default=None, ge=0, le=1)
    change_reason: str | None = None


class MilestoneRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    milestone_id: UUID
    revision_no: int
    title: str
    success_criteria: str
    target_on: date | None = None
    weight: Decimal
    accepted_completion: Decimal
    status: MilestoneStatus
    change_reason: str | None = None
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    milestone_id: UUID | None = None
    assignee_id: UUID | None = None
    title: str
    planned_outcome: str
    acceptance_criteria: str
    effort_weight: Decimal
    status: TaskStatus
    completion_fraction: Decimal | None = None
    completion_reason: str | None = None
    blocker: str | None = None
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    milestone_id: UUID | None = None
    assignee_id: UUID | None = None
    planned_outcome: str = ""
    acceptance_criteria: str = ""
    effort_weight: Decimal = Field(default=Decimal(1), ge=0)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    milestone_id: UUID | None = None
    assignee_id: UUID | None = None
    planned_outcome: str | None = None
    acceptance_criteria: str | None = None
    effort_weight: Decimal | None = Field(default=None, ge=0)
    status: TaskStatus | None = None
    completion_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    completion_reason: str | None = None
    blocker: str | None = None


class ResearchDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    decided_on: date
    decision: str
    rationale: str
    participant_ids: list[UUID]
    related_evidence: dict[str, Any]
    created_at: datetime


class ResearchDecisionIn(BaseModel):
    decision: str = Field(min_length=1)
    rationale: str = ""
    decided_on: date | None = None
    participant_ids: list[UUID] = Field(default_factory=list)
    related_evidence: dict[str, Any] = Field(default_factory=dict)


class ProjectProgressOut(BaseModel):
    """PROJ-06: completion from professor-defined weights, never from student scores."""

    project_id: UUID
    milestone_count: int
    weighted_completion: Decimal | None
    completed_milestones: int
    overdue_milestones: int
    open_blockers: int


class PlanBaselineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID | None = None
    planned_outcome: str
    weight: Decimal
    acceptance_criteria: str
    position: int


class PlanBaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    membership_id: UUID
    period_id: UUID
    version_no: int
    state: BaselineState
    frozen_at: datetime | None = None
    source_entry_id: UUID | None = None
    supersedes_id: UUID | None = None
    change_reason: str | None = None
    proposed_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime
    items: list[PlanBaselineItemOut] = Field(default_factory=list)


class PlanItemIn(BaseModel):
    planned_outcome: str = Field(min_length=1)
    weight: Decimal = Field(default=Decimal(1), ge=0)
    acceptance_criteria: str = ""
    task_id: UUID | None = None


class BaselineChangeIn(BaseModel):
    items: list[PlanItemIn]
    reason: str = Field(min_length=1)
