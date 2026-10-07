"""Evidence tables: the citable references and the chunks retrieval ranks.

A report entry or an attachment version becomes an `EvidenceReference`; its text is split into
`EvidenceChunk` rows carrying the same access label, so retrieval filters on it without a join
(architecture §5.7). The repository connector that once fed this index is gone (ADR 0022).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import Visibility
from app.evidence.index.embeddings import EMBEDDING_DIMENSIONS


class EvidenceSourceKind(StrEnum):
    """Where a piece of evidence came from (architecture §5.7).

    The Postgres enum keeps all five labels: `repository_event`, `decision` and `feedback` name
    sources that no longer exist (repository events since ADR 0022), and dropping a label from an
    enum means rebuilding the type under a table that has rows. Nothing writes them.
    """

    REPORT_ENTRY = "report_entry"
    ARTIFACT_VERSION = "artifact_version"
    REPOSITORY_EVENT = "repository_event"
    DECISION = "decision"
    FEEDBACK = "feedback"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


EVIDENCE_SOURCE_KIND_ENUM = _enum(EvidenceSourceKind, "evidence_source_kind")
VISIBILITY_ENUM = Enum(
    Visibility, name="visibility", values_callable=lambda e: [m.value for m in e]
)


class EvidenceReference(UUIDPrimaryKeyMixin, Base):
    """One citable piece of evidence, carrying the access label it was indexed under.

    Every indexed chunk points at a row here, so the permission filter and the citation come from
    the same record (requirements §9, QA-03). Visibility is copied from the source at ingestion and
    re-synced when the source changes.
    """

    __tablename__ = "evidence_references"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", "source_version"),
        UniqueConstraint("workspace_id", "id"),
        Index("ix_evidence_references_project_id_source_time", "project_id", "source_time"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None]
    owner_student_id: Mapped[UUID | None]
    visibility: Mapped[Visibility] = mapped_column(VISIBILITY_ENUM)
    source_kind: Mapped[EvidenceSourceKind] = mapped_column(EVIDENCE_SOURCE_KIND_ENUM)
    source_id: Mapped[UUID]
    source_version: Mapped[str] = mapped_column(Text, default="")
    locator: Mapped[str] = mapped_column(Text, default="")
    supported_claim: Mapped[str | None] = mapped_column(Text)
    source_time: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvidenceChunk(UUIDPrimaryKeyMixin, Base):
    """A retrievable piece of one evidence reference.

    The access label is denormalised onto the chunk so the filter is part of the ranking query
    rather than a join the caller might forget (architecture §5.7).
    """

    __tablename__ = "evidence_chunks"
    __table_args__ = (
        UniqueConstraint("evidence_ref_id", "chunk_no"),
        ForeignKeyConstraint(
            ["workspace_id", "evidence_ref_id"],
            ["evidence_references.workspace_id", "evidence_references.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_evidence_chunks_scope",
            "workspace_id",
            "project_id",
            "visibility",
            "source_time",
        ),
        Index("ix_evidence_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_evidence_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    evidence_ref_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    owner_student_id: Mapped[UUID | None]
    visibility: Mapped[Visibility] = mapped_column(VISIBILITY_ENUM)
    source_version: Mapped[str] = mapped_column(Text, default="")
    chunk_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # `simple` rather than `english`: reports are written in English and Vietnamese, and English
    # stemming distorts the latter. Revisit with the retrieval benchmark (architecture §17).
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_time: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
