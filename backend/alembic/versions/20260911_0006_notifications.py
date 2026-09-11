"""notifications: in-app messages, email delivery, preferences, reminder rules

Requirements REP-07, REP-08, UI-07; architecture sections 7.2, 7.3, 13.

Revision ID: 8455aacd9d10
Revises: 0005
Create Date: 2026-09-11 18:23:13.887703+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        "notification_preferences",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "muted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_notification_preferences_workspace_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_notification_preferences_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint(
            "user_id", "kind", name=op.f("uq_notification_preferences_user_id_kind")
        ),
    )
    op.create_table(
        "notifications",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject_table", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("period_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "recipient_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_notifications_workspace_id_recipient_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_notifications_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_notifications_workspace_id_id")),
    )
    op.create_index(
        "ix_notifications_recipient_id_created_at",
        "notifications",
        ["recipient_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_notification",
        "notifications",
        ["recipient_id", "period_id", "kind"],
        unique=True,
        postgresql_where=sa.text("period_id IS NOT NULL"),
    )
    op.create_index(
        "uq_notification_subject",
        "notifications",
        ["recipient_id", "kind", "subject_id"],
        unique=True,
        postgresql_where=sa.text("period_id IS NULL"),
    )
    op.create_table(
        "email_deliveries",
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("recipient_email", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column(
            "state", sa.Enum("queued", "sent", "failed", name="delivery_state"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["notifications.workspace_id", "notifications.id"],
            name=op.f("fk_email_deliveries_workspace_id_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_email_deliveries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notification_id", name=op.f("pk_email_deliveries")),
    )
    op.create_index("ix_email_deliveries_state", "email_deliveries", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_email_deliveries_state", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_index(
        "uq_notification_subject",
        table_name="notifications",
        postgresql_where=sa.text("period_id IS NULL"),
    )
    op.drop_index(
        "uq_notification",
        table_name="notifications",
        postgresql_where=sa.text("period_id IS NOT NULL"),
    )
    op.drop_index("ix_notifications_recipient_id_created_at", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_table("reminder_rules")
    op.execute("DROP TYPE IF EXISTS delivery_state")
