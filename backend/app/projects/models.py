"""Project tables: projects, memberships, plan baselines.

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


class MembershipOrigin(StrEnum):
    """How a membership came to exist (PROJ-07).

    It is not bookkeeping. The derivation reads this column to decide which weeks a membership owes
    (`repository.memberships_active_in_range`), and it is how the audit trail tells the three apart,
    since the actor alone cannot.

    `assigned` and `created` owe the week they land in: a professor assigning a student mid-week
    knows what they are asking for, and a student who starts a project is asking for it themselves.
    `self_joined` owes from the following week — joining an existing project on a Saturday should
    not be a report due that Sunday for a week spent off the project.
    """

    ASSIGNED = "assigned"
    SELF_JOINED = "self_joined"
    CREATED = "created"


class BaselineState(StrEnum):
    """PROJ-04, architecture §5.5.

    `frozen` is the plan carried over from the previous report; `empty` records that there was
    nothing to freeze. Only `frozen` and `accepted` count as commitments (ASSESS-05).

    `proposed`, `accepted` and `superseded` belonged to a proposal flow that had no route and no
    screen and was removed in 0.10; nothing writes them now. They stay because this is a Postgres
    enum and `uq_baseline_in_effect` names `accepted`.
    """

    FROZEN = "frozen"
    EMPTY = "empty"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


STAGE_ENUM = _enum(ResearchStage, "research_stage")
PROJECT_STATUS_ENUM = _enum(ProjectStatus, "project_status")
MEMBERSHIP_ORIGIN_ENUM = _enum(MembershipOrigin, "membership_origin")
BASELINE_STATE_ENUM = _enum(BaselineState, "baseline_state")


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
    # Where the code lives, as a link for the people on the project (PROJ-01, shared resources).
    # A URL somebody typed, nothing more: there is no repository connector (ADR 0022), so nothing
    # reads it but a human, and filling it in attributes no commits to anybody.
    repo_url: Mapped[str | None] = mapped_column(Text)
    shared_resources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Architecture §10: every model step is skipped for a restricted project; the professor rates
    # it by hand and the pipeline records "Not rated — restricted".
    ai_restricted: Mapped[bool] = mapped_column(default=False, server_default="false")
    # PROJ-07: whether a student may put themselves on this project without being assigned.
    # Default closed, and only a professor may open it: a membership is the whole grant of access
    # to a project's records, so opening one is a disclosure decision, not a convenience.
    open_to_join: Mapped[bool] = mapped_column(default=False, server_default="false")
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
        # Reporting owns periods, so these bounds are declared by table name and the constraints
        # are added by the migration that creates that table (REP-01).
        ForeignKeyConstraint(
            ["workspace_id", "first_required_period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            ondelete="SET NULL",
            name="fk_memberships_first_required_period",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "last_required_period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            ondelete="SET NULL",
            name="fk_memberships_last_required_period",
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
    origin: Mapped[MembershipOrigin] = mapped_column(
        MEMBERSHIP_ORIGIN_ENUM,
        default=MembershipOrigin.ASSIGNED,
        server_default=MembershipOrigin.ASSIGNED.value,
    )
    joined_on: Mapped[date]
    # Exclusive: the first day the student is no longer a member. Ending a membership today
    # therefore revokes access today (AUTH-03).
    left_on: Mapped[date | None]
    first_required_period_id: Mapped[UUID | None]
    last_required_period_id: Mapped[UUID | None]
    planned_allocation: Mapped[float | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlanBaseline(UUIDPrimaryKeyMixin, Base):
    """PROJ-04: the plan one membership is assessed against for one reporting period.

    Content is immutable, so the commitments originally missed cannot be edited away. `period_id`
    is a reporting period, which the reporting module owns and supplies — the foreign key is added
    by its migration.
    """

    __tablename__ = "plan_baselines"
    __table_args__ = (
        UniqueConstraint("membership_id", "period_id", "version_no"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "membership_id"],
            ["project_memberships.workspace_id", "project_memberships.id"],
            ondelete="CASCADE",
        ),
        # By table name rather than by import: reporting owns periods and sits above projects.
        ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            ondelete="CASCADE",
        ),
        # At most one baseline in effect per membership and period (requirements §9).
        Index(
            "uq_baseline_in_effect",
            "membership_id",
            "period_id",
            unique=True,
            postgresql_where=text("state IN ('frozen', 'accepted')"),
        ),
        Index("ix_plan_baselines_period_id", "period_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    membership_id: Mapped[UUID]
    period_id: Mapped[UUID]
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[BaselineState] = mapped_column(BASELINE_STATE_ENUM)
    frozen_at: Mapped[datetime | None]
    source_entry_id: Mapped[UUID | None]
    supersedes_id: Mapped[UUID | None]
    change_reason: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlanBaselineItem(UUIDPrimaryKeyMixin, Base):
    """One committed outcome and its frozen weight (ASSESS-05). Immutable.

    The outcome is a line of the student's free-text next-week plan. `task_id` is a leftover of
    the tasks table removed in 0.10; it has no foreign key and nothing writes it.
    """

    __tablename__ = "plan_baseline_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "baseline_id"],
            ["plan_baselines.workspace_id", "plan_baselines.id"],
            ondelete="CASCADE",
        ),
        Index("ix_plan_baseline_items_baseline_id", "baseline_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    baseline_id: Mapped[UUID]
    task_id: Mapped[UUID | None]
    planned_outcome: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Numeric(6, 2), default=1)
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
