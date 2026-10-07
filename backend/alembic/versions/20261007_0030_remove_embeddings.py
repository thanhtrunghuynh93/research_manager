"""embeddings and pgvector are removed, with the unqueried full-text column

ADR 0024. Every indexed chunk carried a 1536-dimension embedding (0009), computed by a paid
provider call on the student's upload path, and nothing has read one since hybrid search went
with the research assistant (ADR 0023). The generated `tsv` column and its GIN index were the
other half of that search and have no reader either. Assessment reads chunk text by window, by
source and by reference, through `ix_evidence_chunks_scope`, which stays.

Dropped: `ix_evidence_chunks_embedding` (HNSW) and `evidence_chunks.embedding`;
`ix_evidence_chunks_tsv` (GIN) and `evidence_chunks.tsv`; then the `vector` extension, so the
database no longer needs the pgvector image. Chunk rows and their text are untouched. `IF EXISTS`
throughout because a database created on plain postgres:16 never had the vector column (0009).

Deploy this on the pgvector image first; only then switch the image to postgres:16
(docs/runbooks/deploy.md).

The downgrade needs the pgvector image again: it recreates the extension, the column and the HNSW
index, and the `tsv` column and GIN index exactly as 0009 defined them. The column comes back
NULLable, not NOT NULL as 0009 made it, because the rows that exist have no embedding; code at 0029
writes one for every new chunk, and the existing chunks would need re-embedding before anything
could rank them — which nothing at 0029 does either.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_chunks_embedding")
    op.execute("ALTER TABLE evidence_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("DROP INDEX IF EXISTS ix_evidence_chunks_tsv")
    op.execute("ALTER TABLE evidence_chunks DROP COLUMN IF EXISTS tsv")
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "evidence_chunks",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
    )
    op.execute("ALTER TABLE evidence_chunks ADD COLUMN embedding vector(1536)")
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
        "ix_evidence_chunks_tsv", "evidence_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
