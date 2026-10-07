"""the research assistant (chat) is removed, with the access epoch and supervision notes

ADR 0023. The assistant (QA-01..07) was built in full and never used on the deployment this runs
against: `conversations`, `messages` and `answer_cache` were empty, and so was
`supervision_notes`, which only the assistant read and no screen wrote. The professor overview,
which had borrowed the assistant's fact functions, computes the same numbers in `app.overview`.

Dropped: the four tables, the `message_role` enum (0012; only `messages` used it), and two columns
that existed for the answer cache — `workspaces.access_epoch` (0002), which every change of access
advanced so cached answers could be invalidated, and `evidence_snapshots.access_epoch` (0010),
which recorded it and was never read.

The downgrade restores the shapes as they were at 0028 (0010, 0012 and 0022), not the data. There
was none in the tables; the epochs come back as 1 and 0, the values a fresh row would have had.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_answer_cache_epoch", table_name="answer_cache")
    op.drop_table("answer_cache")
    op.drop_index("ix_messages_conversation", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_owner", table_name="conversations")
    op.drop_table("conversations")
    op.execute("DROP TYPE IF EXISTS message_role")

    op.drop_index("ix_supervision_notes_subject", table_name="supervision_notes")
    op.drop_table("supervision_notes")

    op.drop_column("evidence_snapshots", "access_epoch")
    op.drop_column("workspaces", "access_epoch")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("access_epoch", sa.Integer(), server_default="1", nullable=False),
    )
    # 0010 declared no default; one is needed only to fill the rows that exist now.
    op.add_column(
        "evidence_snapshots",
        sa.Column("access_epoch", sa.Integer(), server_default="0", nullable=False),
    )
    op.alter_column("evidence_snapshots", "access_epoch", server_default=None)

    op.create_table(
        "supervision_notes",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("period_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
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
            name=op.f("fk_supervision_notes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervision_notes")),
    )
    op.create_index(
        "ix_supervision_notes_subject",
        "supervision_notes",
        ["student_id", "project_id"],
        unique=False,
    )

    op.create_table(
        "conversations",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name="fk_conversations_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_conversations_workspace_id_id"),
    )
    op.create_index("ix_conversations_owner", "conversations", ["owner_id", "created_at"])

    op.create_table(
        "messages",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", name="message_role"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name="fk_messages_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "created_at"])

    op.create_table(
        "answer_cache",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("question_hash", sa.Text(), nullable=False),
        sa.Column("scope_hash", sa.Text(), nullable=False),
        sa.Column("access_epoch", sa.Integer(), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        # 0022
        sa.Column("epoch_fingerprint", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_answer_cache_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_answer_cache"),
        sa.UniqueConstraint("user_id", "question_hash", "scope_hash", name="uq_answer_cache_key"),
    )
    op.create_index("ix_answer_cache_epoch", "answer_cache", ["workspace_id", "access_epoch"])
