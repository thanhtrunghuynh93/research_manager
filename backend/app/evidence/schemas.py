"""Request and response models for the evidence API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.types import Visibility

# Re-exported for the API layer, which must not import ORM modules directly.
from app.evidence.models import AttributionState as AttributionState
from app.evidence.models import ConnectionState as ConnectionState
from app.evidence.models import ContributionRole as ContributionRole
from app.evidence.models import ContributionShare as ContributionShare
from app.evidence.models import EventKind as EventKind
from app.evidence.models import EvidenceSourceKind as EvidenceSourceKind
from app.evidence.models import IdentityVerification as IdentityVerification
from app.evidence.models import SyncKind as SyncKind
from app.evidence.models import SyncState as SyncState


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    external_id: str
    full_name: str
    visibility: str
    connection_state: ConnectionState
    default_branch: str | None = None
    created_at: datetime


class RepositoryIn(BaseModel):
    provider: str = "github"
    external_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    default_branch: str | None = None
    credential_ref: str | None = None


class ProjectLinkIn(BaseModel):
    project_id: UUID
    path_rules: list[str] = Field(default_factory=list)


class ProjectLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    project_id: UUID
    path_rules: list[str]


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    kind: SyncKind
    state: SyncState
    watermark: dict[str, Any]
    pages_done: int
    events_ingested: int
    error_summary: str | None = None
    attempt: int
    started_at: datetime
    finished_at: datetime | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    provider_event_id: str
    kind: EventKind
    source_version: str | None = None
    title: str
    actors: list[Any]
    authored_at: datetime | None = None
    committed_at: datetime | None = None
    merged_at: datetime | None = None
    event_at: datetime
    ingested_at: datetime
    paths: list[str]
    stats: dict[str, Any]
    truncated: bool
    live_available: bool
    source_url: str | None = None


class WebhookResult(BaseModel):
    """`accepted` means this delivery was new; a repeat of the same id is False (AC-09).

    `repository_id` is None when the delivery is for a repository this workspace never connected.
    That is not a failure — it is recorded and dropped — but it is the difference between a webhook
    that is doing something and one that is quietly landing nowhere, which is worth being able to
    see from the outside.
    """

    accepted: bool
    delivery_id: str
    repository_id: UUID | None = None
    detail: str = ""


class IdentityIn(BaseModel):
    student_id: UUID
    provider: str = "github"
    login: str | None = None
    email: str | None = None


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    provider: str
    login: str | None = None
    email: str | None = None
    verification: IdentityVerification
    is_bot: bool
    created_at: datetime


class ContributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    student_id: UUID
    project_id: UUID | None = None
    role: ContributionRole
    share: ContributionShare
    attribution_state: AttributionState
    provenance: dict[str, Any]
    created_at: datetime


class EvidenceReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    owner_student_id: UUID | None = None
    visibility: Visibility
    source_kind: EvidenceSourceKind
    source_id: UUID
    source_version: str
    locator: str
    supported_claim: str | None = None
    source_time: datetime
    ingested_at: datetime


class EvidenceHit(BaseModel):
    """One retrieved chunk with everything a citation needs (QA-03)."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    evidence_ref_id: UUID
    text: str
    score: float
    source_kind: EvidenceSourceKind
    source_id: UUID
    source_version: str
    locator: str
    project_id: UUID | None = None
    source_time: datetime
    visibility: Visibility = Visibility.PROJECT_SHARED
