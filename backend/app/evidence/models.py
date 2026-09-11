"""Evidence tables: repositories, sync runs, normalised events, identities, contributions.

Requirements REPO-01..08. `repository_events` is immutable: an event we have already attributed and
cited cannot change underneath the assessment that cites it (architecture §5.3, §8.2).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import Visibility
from app.evidence.index.embeddings import EMBEDDING_DIMENSIONS


class ConnectionState(StrEnum):
    CONNECTED = "connected"
    UNAUTHORIZED = "unauthorized"
    DISCONNECTED = "disconnected"


class SyncKind(StrEnum):
    INITIAL = "initial"
    INCREMENTAL = "incremental"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class SyncState(StrEnum):
    """Job states the requirements ask to be distinguishable (requirements §10)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class EventKind(StrEnum):
    COMMIT = "commit"
    PR_OPENED = "pr_opened"
    PR_MERGED = "pr_merged"
    REVIEW = "review"
    ISSUE = "issue"
    CHECK_RUN = "check_run"
    PUSH_FORCE = "push_force"


class EvidenceSourceKind(StrEnum):
    """Where a piece of evidence came from (architecture §5.7)."""

    REPORT_ENTRY = "report_entry"
    ARTIFACT_VERSION = "artifact_version"
    REPOSITORY_EVENT = "repository_event"
    DECISION = "decision"
    FEEDBACK = "feedback"


class IdentityVerification(StrEnum):
    """REPO-03: how far we trust that this provider account is this student."""

    PENDING = "pending"
    VERIFIED_OAUTH = "verified_oauth"
    CONFIRMED_BY_STUDENT = "confirmed_by_student"
    CONFIRMED_BY_PROF = "confirmed_by_prof"
    REJECTED = "rejected"


class ContributionRole(StrEnum):
    AUTHOR = "author"
    COMMITTER = "committer"
    REVIEWER = "reviewer"
    MERGER = "merger"


class ContributionShare(StrEnum):
    INDIVIDUAL = "individual"
    JOINT = "joint"


class AttributionState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED_IDENTITY = "unresolved_identity"
    UNRESOLVED_PROJECT = "unresolved_project"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


CONNECTION_STATE_ENUM = _enum(ConnectionState, "connection_state")
SYNC_KIND_ENUM = _enum(SyncKind, "sync_kind")
SYNC_STATE_ENUM = _enum(SyncState, "sync_state")
EVENT_KIND_ENUM = _enum(EventKind, "event_kind")
IDENTITY_VERIFICATION_ENUM = _enum(IdentityVerification, "identity_verification")
CONTRIBUTION_ROLE_ENUM = _enum(ContributionRole, "contribution_role")
CONTRIBUTION_SHARE_ENUM = _enum(ContributionShare, "contribution_share")
ATTRIBUTION_STATE_ENUM = _enum(AttributionState, "attribution_state")
EVIDENCE_SOURCE_KIND_ENUM = _enum(EvidenceSourceKind, "evidence_source_kind")
VISIBILITY_ENUM = Enum(
    Visibility, name="visibility", values_callable=lambda e: [m.value for m in e]
)


class Repository(UUIDPrimaryKeyMixin, Base):
    """REPO-01: a connected repository. Credentials are referenced, never stored here."""

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "external_id"),
        UniqueConstraint("workspace_id", "id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, default="private")
    connection_state: Mapped[ConnectionState] = mapped_column(
        CONNECTION_STATE_ENUM, default=ConnectionState.CONNECTED
    )
    # The name of a secret in the protected store, never the secret (requirements §9).
    credential_ref: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(Text)
    connected_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProjectRepository(UUIDPrimaryKeyMixin, Base):
    """REPO-04: which project a repository's work belongs to, and how to tell when it serves more
    than one. Unmatched paths leave the attribution unresolved rather than guessing."""

    __tablename__ = "project_repositories"
    __table_args__ = (
        UniqueConstraint("repository_id", "project_id"),
        ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            ondelete="CASCADE",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    repository_id: Mapped[UUID]
    project_id: Mapped[UUID]
    path_rules: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SyncRun(UUIDPrimaryKeyMixin, Base):
    """REPO-05: what was covered, how far it got, and why it stopped (architecture §8.3)."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            ondelete="CASCADE",
        ),
        Index("ix_sync_runs_repository_id_started_at", "repository_id", "started_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    repository_id: Mapped[UUID]
    kind: Mapped[SyncKind] = mapped_column(SYNC_KIND_ENUM)
    state: Mapped[SyncState] = mapped_column(SYNC_STATE_ENUM, default=SyncState.QUEUED)
    watermark: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    events_ingested: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class RepositoryEvent(UUIDPrimaryKeyMixin, Base):
    """REPO-02/06: one normalised source event, with every date the provider gave us kept apart.

    `provider_event_id` is the idempotency key: reprocessing the same source event inserts nothing
    (REPO-05, AC-09).
    """

    __tablename__ = "repository_events"
    __table_args__ = (
        UniqueConstraint("repository_id", "provider_event_id"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            ondelete="CASCADE",
        ),
        Index("ix_repository_events_repository_id_event_at", "repository_id", "event_at"),
        Index("ix_repository_events_source_version", "source_version"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    repository_id: Mapped[UUID]
    provider_event_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[EventKind] = mapped_column(EVENT_KIND_ENUM)
    source_version: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    # [{role, login, email, name, is_bot}] exactly as the provider reported them (REPO-03).
    actors: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    authored_at: Mapped[datetime | None]
    committed_at: Mapped[datetime | None]
    merged_at: Mapped[datetime | None]
    event_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    paths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    # Raw counts are activity statistics only, never evidence of progress (REPO-07, AC-14).
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload_key: Mapped[str | None] = mapped_column(Text)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    live_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    source_url: Mapped[str | None] = mapped_column(Text)


class WebhookDelivery(UUIDPrimaryKeyMixin, Base):
    """REPO-05: deliveries are deduplicated on the provider's delivery id before any work."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("provider", "delivery_id"),
        Index("ix_webhook_deliveries_received_at", "received_at"),
    )

    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(Text)
    delivery_id: Mapped[str] = mapped_column(Text)
    event: Mapped[str] = mapped_column(Text)
    external_repo_id: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DeveloperIdentity(UUIDPrimaryKeyMixin, Base):
    """REPO-03: which provider account is which student, and how well we know it."""

    __tablename__ = "developer_identities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "login"),
        UniqueConstraint("workspace_id", "provider", "email"),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_developer_identities_student_id", "student_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID]
    provider: Mapped[str] = mapped_column(Text)
    login: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    verification: Mapped[IdentityVerification] = mapped_column(
        IDENTITY_VERIFICATION_ENUM, default=IdentityVerification.PENDING
    )
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    confirmed_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Contribution(UUIDPrimaryKeyMixin, Base):
    """REPO-04: what one student did in one event, and how confident the attribution is.

    A row per (student, event, role): merging someone else's change records a `merger` role, which
    is not authorship (AC-06).
    """

    __tablename__ = "contributions"
    __table_args__ = (
        UniqueConstraint("event_id", "student_id", "role"),
        ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["repository_events.workspace_id", "repository_events.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_contributions_student_id_project_id", "student_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    event_id: Mapped[UUID]
    student_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    role: Mapped[ContributionRole] = mapped_column(CONTRIBUTION_ROLE_ENUM)
    share: Mapped[ContributionShare] = mapped_column(
        CONTRIBUTION_SHARE_ENUM, default=ContributionShare.INDIVIDUAL
    )
    attribution_state: Mapped[AttributionState] = mapped_column(
        ATTRIBUTION_STATE_ENUM, default=AttributionState.RESOLVED
    )
    # How the attribution was reached, so a student can challenge it (REPO-04).
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
