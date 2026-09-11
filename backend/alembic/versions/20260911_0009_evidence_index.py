"""evidence index: citable references and their searchable chunks

Requirements AUTH-02, QA-02, QA-03, QA-06; architecture section 5.7.

Revision ID: e1cbb35a878b
Revises: 0008
Create Date: 2026-09-11 18:54:18.606129+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_references",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("owner_student_id", sa.UUID(), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("professor_only", "student_private", "project_shared", name="visibility"),
            nullable=False,
        ),
        sa.Column(
            "source_kind",
            sa.Enum(
                "report_entry",
                "artifact_version",
                "repository_event",
                "decision",
                "feedback",
                name="evidence_source_kind",
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("supported_claim", sa.Text(), nullable=True),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_evidence_references_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_references")),
        sa.UniqueConstraint(
            "source_kind",
            "source_id",
            "source_version",
            name=op.f("uq_evidence_references_source_kind_source_id_source_version"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_evidence_references_workspace_id_id")
        ),
    )
    op.create_index(
        "ix_evidence_references_project_id_source_time",
        "evidence_references",
        ["project_id", "source_time"],
        unique=False,
    )
    op.create_table(
        "evidence_chunks",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("evidence_ref_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("owner_student_id", sa.UUID(), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("professor_only", "student_private", "project_shared", name="visibility"),
            nullable=False,
        ),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("chunk_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evidence_ref_id"],
            ["evidence_references.workspace_id", "evidence_references.id"],
            name=op.f("fk_evidence_chunks_workspace_id_evidence_ref_id_evidence_references"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_evidence_chunks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_chunks")),
        sa.UniqueConstraint(
            "evidence_ref_id", "chunk_no", name=op.f("uq_evidence_chunks_evidence_ref_id_chunk_no")
        ),
    )
    op.create_index(
        "ix_evidence_chunks_embedding",
        "evidence_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_evidence_chunks_scope",
        "evidence_chunks",
        ["workspace_id", "project_id", "visibility", "source_time"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_chunks_tsv", "evidence_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_chunks_tsv", table_name="evidence_chunks", postgresql_using="gin")
    op.drop_index("ix_evidence_chunks_scope", table_name="evidence_chunks")
    op.drop_index(
        "ix_evidence_chunks_embedding",
        table_name="evidence_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("evidence_chunks")
    op.drop_index("ix_evidence_references_project_id_source_time", table_name="evidence_references")
    op.drop_table("evidence_references")
    op.execute("DROP TYPE IF EXISTS evidence_source_kind")
    op.execute("DROP TYPE IF EXISTS visibility")
