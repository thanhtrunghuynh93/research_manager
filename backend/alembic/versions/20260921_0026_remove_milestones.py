"""projects: milestones are removed

The feature was built and never used: on the deployment this runs against, `milestones`,
`milestone_revisions`, `tasks.milestone_id` and `project_report_entries.milestone_ids` were all
empty, and no screen wrote any of them — `accepted_completion`, the number the project's progress
figure was computed from, was settable only through an endpoint the frontend never called.

What goes with them: the `milestone_status` enum, the two tables, the task foreign key, and the
array on the report entry. What stays: tasks, which a plan baseline freezes (PROJ-04) and which
only ever pointed at a milestone optionally.

`project_report_entries` is otherwise immutable and guarded by a trigger, but the guard is on rows
rather than on the table definition, so dropping a column does not fight it. The column's removal
also changes `CONTENT_FIELDS`, the tuple the entry's `content_hash` is computed over: an entry
written before this and hashed again after it will hash differently, so the first resubmission of
an existing week will look changed and re-assess that entry once (ASSESS-09). Harmless, and worth
knowing before somebody wonders why.

The downgrade restores the shapes, not the data. There was none.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("project_report_entries", "milestone_ids")
    op.drop_index("ix_tasks_milestone_id", table_name="tasks")
    op.drop_column("tasks", "milestone_id")
    op.drop_table("milestone_revisions")
    op.drop_table("milestones")
    sa.Enum(name="milestone_status").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    milestone_status = postgresql.ENUM(
        "planned",
        "in_progress",
        "at_risk",
        "completed",
        "cancelled",
        name="milestone_status",
        create_type=False,
    )
    milestone_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "contributor_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column("status", milestone_status, nullable=False, server_default="planned"),
        sa.Column("success_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("weight", sa.Numeric(6, 2), nullable=False, server_default="1"),
        sa.Column("accepted_completion", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("revision_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"], ["projects.workspace_id", "projects.id"]
        ),
    )
    op.create_index("ix_milestones_project_id_status", "milestones", ["project_id", "status"])

    op.create_table(
        "milestone_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("success_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column("weight", sa.Numeric(6, 2), nullable=False),
        sa.Column("accepted_completion", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", milestone_status, nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["milestone_id"], ["milestones.id"], ondelete="CASCADE"),
    )

    op.add_column("tasks", sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"])
    op.add_column(
        "project_report_entries",
        sa.Column(
            "milestone_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )
