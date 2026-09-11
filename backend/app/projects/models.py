"""Project tables: projects, memberships, milestones, tasks, research decisions.

Requirements PROJ-01..06. Only this module imports these classes; other modules read them through
projects.service (docs/repo_layout.md §3.2).
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
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class ResearchStage(StrEnum):
    """The stages the system must support (requirements §1); the rubric adapts to each (PROJ-05)."""

    LITERATURE_REVIEW = "literature_review"
    THEORY = "theory"
    DATA_PREPARATION = "data_preparation"
    IMPLEMENTATION = "implementation"
    EXPERIMENTATION = "experimentation"
    ANALYSIS = "analysis"
    WRITING = "writing"


class ProjectStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MilestoneStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    AT_RISK = "at_risk"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    DROPPED = "dropped"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


STAGE_ENUM = _enum(ResearchStage, "research_stage")
PROJECT_STATUS_ENUM = _enum(ProjectStatus, "project_status")
MILESTONE_STATUS_ENUM = _enum(MilestoneStatus, "milestone_status")
TASK_STATUS_ENUM = _enum(TaskStatus, "task_status")


def _workspace_scoped_project_fk() -> ForeignKeyConstraint:
    """(workspace_id, project_id) -> projects(workspace_id, id): the same-workspace invariant."""
    return ForeignKeyConstraint(
        ["workspace_id", "project_id"],
        ["projects.workspace_id", "projects.id"],
        ondelete="CASCADE",
    )


class Project(UUIDPrimaryKeyMixin, Base):
    """PROJ-01: goals, stage, status, dates, and the shared resources of one research project."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of composite foreign keys
        Index("ix_projects_workspace_id_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    research_questions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    intended_contributions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    stage: Mapped[ResearchStage] = mapped_column(STAGE_ENUM)
    status: Mapped[ProjectStatus] = mapped_column(
        PROJECT_STATUS_ENUM, default=ProjectStatus.PROPOSED
    )
    start_on: Mapped[date | None]
    target_on: Mapped[date | None]
    venue_target: Mapped[str | None] = mapped_column(Text)
    shared_resources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Architecture §10: every model step is skipped for a restricted project; the professor rates
    # it by hand and the pipeline records "Not rated — restricted".
    ai_restricted: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProjectMembership(UUIDPrimaryKeyMixin, Base):
    """PROJ-02: one student's participation, kept as history rather than deleted when they leave.

    `first_required_period_id` and `last_required_period_id` bound the weeks this membership owes a
    report (REP-01). They are plain identifiers until the reporting module creates
    `reporting_periods`, which then adds the foreign keys.
    """

    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        _workspace_scoped_project_fk(),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
        ),
        # PROJ-02: one active membership per student per project; history rows carry left_on.
        Index(
            "uq_membership_active",
            "project_id",
            "student_id",
            unique=True,
            postgresql_where=text("left_on IS NULL"),
        ),
        Index("ix_project_memberships_student_id", "student_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID]
    student_id: Mapped[UUID]
    responsibility: Mapped[str] = mapped_column(Text, default="")
    joined_on: Mapped[date]
    # Exclusive: the first day the student is no longer a member. Ending a membership today
    # therefore revokes access today (AUTH-03).
    left_on: Mapped[date | None]
    first_required_period_id: Mapped[UUID | None]
    last_required_period_id: Mapped[UUID | None]
    planned_allocation: Mapped[float | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Milestone(UUIDPrimaryKeyMixin, Base):
    """PROJ-03/PROJ-06: an owned outcome with success criteria, a weight, and accepted progress."""

    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        _workspace_scoped_project_fk(),
        Index("ix_milestones_project_id_status", "project_id", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[UUID | None]
    contributor_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default="{}"
    )
    target_on: Mapped[date | None]
    status: Mapped[MilestoneStatus] = mapped_column(
        MILESTONE_STATUS_ENUM, default=MilestoneStatus.PLANNED
    )
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    # PROJ-06: project completion is computed from these weights and accepted fractions, never
    # from average student scores.
    weight: Mapped[float] = mapped_column(Numeric(6, 2), default=1)
    accepted_completion: Mapped[float] = mapped_column(Numeric(3, 2), default=0)
    revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class MilestoneRevision(UUIDPrimaryKeyMixin, Base):
    """PROJ-06: the baseline kept when milestone scope or weights change. Immutable."""

    __tablename__ = "milestone_revisions"
    __table_args__ = (
        UniqueConstraint("milestone_id", "revision_no"),
        Index("ix_milestone_revisions_milestone_id", "milestone_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    milestone_id: Mapped[UUID]
    revision_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    target_on: Mapped[date | None]
    weight: Mapped[float] = mapped_column(Numeric(6, 2))
    accepted_completion: Mapped[float] = mapped_column(Numeric(3, 2))
    status: Mapped[MilestoneStatus] = mapped_column(MILESTONE_STATUS_ENUM)
    change_reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Task(UUIDPrimaryKeyMixin, Base):
    """PROJ-03: weekly work linked to a milestone, with effort weight and completion criteria."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        _workspace_scoped_project_fk(),
        Index("ix_tasks_project_id_status", "project_id", "status"),
        Index("ix_tasks_milestone_id", "milestone_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID]
    milestone_id: Mapped[UUID | None]
    assignee_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(Text)
    planned_outcome: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    effort_weight: Mapped[float] = mapped_column(Numeric(6, 2), default=1)
    status: Mapped[TaskStatus] = mapped_column(TASK_STATUS_ENUM, default=TaskStatus.PLANNED)
    # PROJ-03: completion may be partial and must carry a reason; the fraction only becomes
    # accepted when the professor approves the assessment (ASSESS-05).
    completion_fraction: Mapped[float | None] = mapped_column(Numeric(3, 2))
    completion_reason: Mapped[str | None] = mapped_column(Text)
    blocker: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ResearchDecision(UUIDPrimaryKeyMixin, Base):
    """A dated decision and its rationale.

    This is what answers "why did the project change direction?" with sources (QA-01).
    """

    __tablename__ = "research_decisions"
    __table_args__ = (
        _workspace_scoped_project_fk(),
        Index("ix_research_decisions_project_id_decided_on", "project_id", "decided_on"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID]
    decided_on: Mapped[date]
    decision: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    participant_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default="{}"
    )
    related_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
