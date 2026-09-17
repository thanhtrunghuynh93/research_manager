"""identity: an account can join another workspace

ADR 0014, superseding ADR 0013. Which workspace a professor is in becomes a property of the
account again, which means `users.workspace_id` has to be updatable — and it was not. Eight tables
carry a composite foreign key onto `users(workspace_id, id)` and none cascaded on update, so
Postgres refused the change while any child row existed. Enrolment is invitation-only, so every
account has an `invitations` row from creation and the update was refused for everyone.

Four of those eight hold identity records — an invitation, a session, a reset link, a notification
— which belong to the person rather than to the work. They now cascade, so they follow the account.

The other four are deliberately left alone:

    project_memberships   weekly_reports   developer_identities   contributions

They hold research history, and history stays in the workspace it was written in. Leaving them
blocking is what still refuses to move a student who has submitted anything, which is the rule
recorded in use_cases.md §2.1 — now enforced by the schema rather than by a check.

`sessions.active_workspace_id` goes with them. It existed only because the account could not move
(ADR 0013); now that it can, a session pointing somewhere other than its account is a second
source of truth for the same question.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint name, the column paired with workspace_id)
_IDENTITY_KEYS = [
    ("invitations", "fk_invitations_workspace_id_user_id_users", "user_id"),
    ("sessions", "fk_sessions_workspace_id_user_id_users", "user_id"),
    ("password_resets", "fk_password_resets_workspace_id_user_id_users", "user_id"),
    ("notifications", "fk_notifications_workspace_id_recipient_id_users", "recipient_id"),
]


def upgrade() -> None:
    for table, name, column in _IDENTITY_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            "users",
            ["workspace_id", column],
            ["workspace_id", "id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )

    op.drop_constraint("fk_sessions_active_workspace_id_workspaces", "sessions", type_="foreignkey")
    op.drop_column("sessions", "active_workspace_id")


def downgrade() -> None:
    op.add_column("sessions", sa.Column("active_workspace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sessions_active_workspace_id_workspaces",
        "sessions",
        "workspaces",
        ["active_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for table, name, column in _IDENTITY_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            "users",
            ["workspace_id", column],
            ["workspace_id", "id"],
            ondelete="CASCADE",
        )
