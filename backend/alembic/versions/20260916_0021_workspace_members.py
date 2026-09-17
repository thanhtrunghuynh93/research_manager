"""identity: an account can belong to several workspaces

ADR 0015. `users.workspace_id` was the only record of belonging, so a professor was in exactly one
workspace and joining another moved them out of the last. `workspace_members` records belonging;
`users.workspace_id` keeps its other job, naming the workspace a Scope is compiled from and
anchoring every composite foreign key in the schema.

Backfill writes one membership per existing account from that column, so nobody's belonging
changes when this runs — a student keeps their single membership and a professor gains one for the
workspace they were already in.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "user_id"),
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    # Every existing account belongs to the workspace it was in. uuid7 is not available in SQL, so
    # the ids come from gen_random_uuid(); nothing orders this table by primary key.
    op.execute(
        """
        INSERT INTO workspace_members (id, workspace_id, user_id, created_at)
        SELECT gen_random_uuid(), u.workspace_id, u.id, u.created_at FROM users u
        """
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_table("workspace_members")
