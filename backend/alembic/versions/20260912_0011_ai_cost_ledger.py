"""ai: the cost ledger and the workspace spending budgets

Requirements §11 "Cost control"; architecture §10; ADR 0007.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-12 09:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "ai_budgets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    op.create_table(
        "ai_calls",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        # No foreign key to projects: the ledger observes a call, it does not own the project,
        # and an accounting row must not block a retention sweep.
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        # Null means the model has no published rate here, not that the call was free.
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "completed",
                "failed",
                "invalid_output",
                "delayed_budget",
                "restricted",
                name="ai_call_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "redactions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
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
            name="fk_ai_calls_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_calls"),
    )
    op.create_index("ix_ai_calls_workspace_created", "ai_calls", ["workspace_id", "created_at"])
    op.create_index("ix_ai_calls_project_created", "ai_calls", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_calls_project_created", table_name="ai_calls")
    op.drop_index("ix_ai_calls_workspace_created", table_name="ai_calls")
    op.drop_table("ai_calls")
    op.execute("DROP TYPE IF EXISTS ai_call_status")
    op.drop_column("workspaces", "ai_budgets")
