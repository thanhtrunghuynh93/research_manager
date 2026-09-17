"""identity: a session can act in a workspace other than the account's own

ADR 0013. `users.workspace_id` cannot change — it is the parent of a composite foreign key on
eight tables, none of which cascades on update — so "which workspace am I in" moves onto the
session instead of the account. NULL means the account's own, which is what every session meant
before this column existed.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("active_workspace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sessions_active_workspace_id_workspaces",
        "sessions",
        "workspaces",
        ["active_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_active_workspace_id_workspaces", "sessions", type_="foreignkey")
    op.drop_column("sessions", "active_workspace_id")
