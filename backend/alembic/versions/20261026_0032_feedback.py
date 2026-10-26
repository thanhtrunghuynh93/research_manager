"""feedback: professor feedback on reports, with revisions, files and idempotency keys

ADR 0026. `feedbacks` is the identity and holds the draft's version and the published one;
`feedback_revisions` keeps every state; files are `feedback_attachments`, linked to the revisions
that carry them. All keys are composite on workspace_id, so a row cannot point across workspaces.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _workspace() -> sa.Column[sa.UUID]:
    return sa.Column("workspace_id", sa.UUID(), nullable=False)


def _workspace_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=op.f(f"fk_{table}_workspace_id_workspaces"),
        ondelete="CASCADE",
    )


def _composite_fk(
    table: str, column: str, target: str, target_column: str = "id"
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", column],
        [f"{target}.workspace_id", f"{target}.{target_column}"],
        name=op.f(f"fk_{table}_workspace_id_{column}_{target}"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.UUID(), nullable=False),
        _workspace(),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _created_at("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedbacks")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_feedbacks_workspace_id_id")),
        _workspace_fk("feedbacks"),
        _composite_fk("feedbacks", "student_id", "users"),
        _composite_fk("feedbacks", "project_id", "projects"),
    )
    op.create_index(
        "ix_feedbacks_workspace_id_student_id", "feedbacks", ["workspace_id", "student_id"]
    )
    op.create_index("ix_feedbacks_project_id", "feedbacks", ["project_id"])

    op.create_table(
        "feedback_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        _workspace(),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("report_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        _created_at(),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_revisions")),
        sa.UniqueConstraint(
            "feedback_id", "version_no", name=op.f("uq_feedback_revisions_feedback_id_version_no")
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_feedback_revisions_workspace_id_id")
        ),
        _workspace_fk("feedback_revisions"),
        _composite_fk("feedback_revisions", "feedback_id", "feedbacks"),
    )

    op.create_table(
        "feedback_attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        _workspace(),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        _created_at(),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'ready')", name=op.f("ck_feedback_attachments_state")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_attachments")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_feedback_attachments_workspace_id_id")
        ),
        _workspace_fk("feedback_attachments"),
        _composite_fk("feedback_attachments", "feedback_id", "feedbacks"),
    )
    op.create_index(
        "ix_feedback_attachments_feedback_id", "feedback_attachments", ["feedback_id"]
    )

    op.create_table(
        "feedback_revision_attachments",
        _workspace(),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("attachment_id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint(
            "revision_id", "attachment_id", name=op.f("pk_feedback_revision_attachments")
        ),
        _workspace_fk("feedback_revision_attachments"),
        _composite_fk("feedback_revision_attachments", "revision_id", "feedback_revisions"),
        _composite_fk("feedback_revision_attachments", "attachment_id", "feedback_attachments"),
    )
    op.create_index(
        "ix_feedback_revision_attachments_attachment_id",
        "feedback_revision_attachments",
        ["attachment_id"],
    )

    op.create_table(
        "feedback_idempotency",
        sa.Column("id", sa.UUID(), nullable=False),
        _workspace(),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_idempotency")),
        sa.UniqueConstraint(
            "workspace_id",
            "actor_id",
            "operation",
            "key",
            name=op.f("uq_feedback_idempotency_workspace_id_actor_id_operation_key"),
        ),
        _workspace_fk("feedback_idempotency"),
    )


def downgrade() -> None:
    for table in (
        "feedback_idempotency",
        "feedback_revision_attachments",
        "feedback_attachments",
        "feedback_revisions",
        "feedbacks",
    ):
        op.drop_table(table)
