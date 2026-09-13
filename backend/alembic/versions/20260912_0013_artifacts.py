"""reporting: artifacts and their versions

Requirements REP-04; architecture §5.6.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12 14:05:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("owner_student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("entry_id", sa.UUID(), nullable=True),
        sa.Column("period_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Enum("upload", "link", name="artifact_kind"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("supported_claim", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("current_version_no", sa.Integer(), nullable=False),
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
            name="fk_artifacts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_artifacts_workspace_id_id"),
    )
    op.create_index("ix_artifacts_owner", "artifacts", ["owner_student_id", "created_at"])
    op.create_index("ix_artifacts_project", "artifacts", ["project_id"])

    op.create_table(
        "artifact_versions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        # REP-04: an extraction failure is recorded rather than left as empty text.
        sa.Column(
            "extraction_state",
            sa.Enum("pending", "ok", "failed", "unsupported", name="extraction_state"),
            nullable=False,
        ),
        sa.Column("extracted_text_key", sa.Text(), nullable=True),
        sa.Column("extraction_note", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default="false", nullable=False),
        # False until the upload is confirmed: a presigned URL is a grant, not a fact.
        sa.Column("uploaded", sa.Boolean(), server_default="false", nullable=False),
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
            name="fk_artifact_versions_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "artifact_id"],
            ["artifacts.workspace_id", "artifacts.id"],
            name="fk_artifact_versions_workspace_id_artifact_id_artifacts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_versions"),
        sa.UniqueConstraint(
            "artifact_id", "version_no", name="uq_artifact_versions_artifact_id_version_no"
        ),
    )


def downgrade() -> None:
    op.drop_table("artifact_versions")
    op.drop_index("ix_artifacts_project", table_name="artifacts")
    op.drop_index("ix_artifacts_owner", table_name="artifacts")
    op.drop_table("artifacts")
    op.execute("DROP TYPE IF EXISTS extraction_state")
    op.execute("DROP TYPE IF EXISTS artifact_kind")
