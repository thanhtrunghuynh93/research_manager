"""tasks, research decisions, reminder rules and feedback are removed

Four features that were built, had no screen, and had no reader: on the deployment this runs
against all four tables were empty.

- `tasks` (PROJ-03). No screen created one. A plan baseline freezes the student's free-text
  next-week plan, not tasks; `plan_baseline_items.task_id` stays as a plain column with no foreign
  key, as it always was.
- `research_decisions`. Written only by an endpoint no screen called, and read by a panel that was
  never drawn.
- `reminder_rules` (REP-07). The offsets configured pre-deadline reminder rows that nothing
  displayed or emailed. The missed-deadline email (REP-08) does not read this table.
- `feedback` (ASSESS-08 correction requests). No screen filed one, and the thread that would have
  shown them was never reachable.

The `task_status` and `feedback_kind` enums go with their tables. `visibility` stays: the evidence
index shares it.

The downgrade restores the shapes as they were at 0026, not the data. There was none.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_tasks_project_id_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_research_decisions_project_id_decided_on", table_name="research_decisions")
    op.drop_table("research_decisions")
    op.drop_table("reminder_rules")
    op.drop_index("ix_feedback_subject", table_name="feedback")
    op.drop_index("ix_feedback_recipient", table_name="feedback")
    op.drop_table("feedback")
    sa.Enum(name="task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="feedback_kind").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    task_status = postgresql.ENUM(
        "planned",
        "in_progress",
        "blocked",
        "done",
        "dropped",
        name="task_status",
        create_type=False,
    )
    task_status.create(op.get_bind(), checkfirst=True)
    feedback_kind = postgresql.ENUM(
        "professor_comment",
        "student_response",
        "correction_request",
        name="feedback_kind",
        create_type=False,
    )
    feedback_kind.create(op.get_bind(), checkfirst=True)

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
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("planned_outcome", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("effort_weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("status", task_status, nullable=False),
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
    op.create_index("ix_tasks_project_id_status", "tasks", ["project_id", "status"], unique=False)

    op.create_table(
        "reminder_rules",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
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
            name=op.f("fk_reminder_rules_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_rules")),
        sa.UniqueConstraint(
            "workspace_id",
            "offset_minutes",
            name=op.f("uq_reminder_rules_workspace_id_offset_minutes"),
        ),
    )

    op.create_table(
        "feedback",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("subject_table", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=True),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("kind", feedback_kind, nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM(
                "professor_only",
                "student_private",
                "project_shared",
                name="visibility",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("responds_to_id", sa.UUID(), nullable=True),
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
            name=op.f("fk_feedback_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index("ix_feedback_recipient", "feedback", ["recipient_id"], unique=False)
    op.create_index(
        "ix_feedback_subject", "feedback", ["subject_table", "subject_id"], unique=False
    )
