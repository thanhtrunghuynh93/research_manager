"""projects: projects, memberships, milestones, tasks, decisions

Requirements PROJ-01..06; architecture section 5.1.

Revision ID: 2b5388005b0a
Revises: 0002
Create Date: 2026-09-11 17:44:16.895798+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MILESTONE_REVISIONS_ARE_IMMUTABLE = (
    "CREATE TRIGGER trg_immutable BEFORE UPDATE OR DELETE ON milestone_revisions "
    "FOR EACH ROW EXECUTE FUNCTION raise_immutable()"
)


def upgrade() -> None:
    op.create_table(
        "milestone_revisions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("milestone_id", sa.UUID(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("success_criteria", sa.Text(), nullable=False),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column("weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("accepted_completion", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "in_progress",
                "at_risk",
                "completed",
                "cancelled",
                name="milestone_status",
            ),
            nullable=False,
        ),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_milestone_revisions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_milestone_revisions")),
        sa.UniqueConstraint(
            "milestone_id",
            "revision_no",
            name=op.f("uq_milestone_revisions_milestone_id_revision_no"),
        ),
    )
    op.create_index(
        "ix_milestone_revisions_milestone_id", "milestone_revisions", ["milestone_id"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "research_questions", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "intended_contributions",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                "literature_review",
                "theory",
                "data_preparation",
                "implementation",
                "experimentation",
                "analysis",
                "writing",
                name="research_stage",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("proposed", "active", "paused", "completed", "archived", name="project_status"),
            nullable=False,
        ),
        sa.Column("start_on", sa.Date(), nullable=True),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column("venue_target", sa.Text(), nullable=True),
        sa.Column("shared_resources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ai_restricted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_projects_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_projects_workspace_id_id")),
    )
    op.create_index(
        "ix_projects_workspace_id_status", "projects", ["workspace_id", "status"], unique=False
    )
    op.create_table(
        "milestones",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column(
            "contributor_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "in_progress",
                "at_risk",
                "completed",
                "cancelled",
                name="milestone_status",
            ),
            nullable=False,
        ),
        sa.Column("success_criteria", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("accepted_completion", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("revision_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_milestones_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_milestones_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_milestones")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_milestones_workspace_id_id")),
    )
    op.create_index(
        "ix_milestones_project_id_status", "milestones", ["project_id", "status"], unique=False
    )
    op.create_table(
        "project_memberships",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("responsibility", sa.Text(), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("first_required_period_id", sa.UUID(), nullable=True),
        sa.Column("last_required_period_id", sa.UUID(), nullable=True),
        sa.Column("planned_allocation", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_project_memberships_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_project_memberships_workspace_id_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_memberships_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_memberships")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_project_memberships_workspace_id_id")
        ),
    )
    op.create_index(
        "ix_project_memberships_student_id", "project_memberships", ["student_id"], unique=False
    )
    op.create_index(
        "uq_membership_active",
        "project_memberships",
        ["project_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("left_on IS NULL"),
    )
    op.create_table(
        "research_decisions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("decided_on", sa.Date(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "participant_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column("related_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_research_decisions_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_research_decisions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_decisions")),
    )
    op.create_index(
        "ix_research_decisions_project_id_decided_on",
        "research_decisions",
        ["project_id", "decided_on"],
        unique=False,
    )
    op.create_table(
        "tasks",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("milestone_id", sa.UUID(), nullable=True),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("planned_outcome", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("effort_weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("planned", "in_progress", "blocked", "done", "dropped", name="task_status"),
            nullable=False,
        ),
        sa.Column("completion_fraction", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("completion_reason", sa.Text(), nullable=True),
        sa.Column("blocker", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_tasks_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tasks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_tasks_workspace_id_id")),
    )
    op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"], unique=False)
    op.create_index("ix_tasks_project_id_status", "tasks", ["project_id", "status"], unique=False)

    # PROJ-06: a retained baseline that could be edited is not a baseline.
    op.execute(MILESTONE_REVISIONS_ARE_IMMUTABLE)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_immutable ON milestone_revisions")
    op.drop_index("ix_tasks_project_id_status", table_name="tasks")
    op.drop_index("ix_tasks_milestone_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_research_decisions_project_id_decided_on", table_name="research_decisions")
    op.drop_table("research_decisions")
    op.drop_index(
        "uq_membership_active",
        table_name="project_memberships",
        postgresql_where=sa.text("left_on IS NULL"),
    )
    op.drop_index("ix_project_memberships_student_id", table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_index("ix_milestones_project_id_status", table_name="milestones")
    op.drop_table("milestones")
    op.drop_index("ix_projects_workspace_id_status", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_milestone_revisions_milestone_id", table_name="milestone_revisions")
    op.drop_table("milestone_revisions")
    for enum_name in ("task_status", "milestone_status", "project_status", "research_stage"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
