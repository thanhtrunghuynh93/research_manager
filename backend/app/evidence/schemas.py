"""Request and response models for the evidence API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.types import Visibility

# Re-exported for the API layer, which must not import ORM modules directly.
from app.evidence.models import EvidenceSourceKind as EvidenceSourceKind


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
    """One indexed chunk with everything a citation in an assessment needs (ASSESS-02)."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    evidence_ref_id: UUID
    text: str
    source_kind: EvidenceSourceKind
    source_id: UUID
    source_version: str
    locator: str
    project_id: UUID | None = None
    source_time: datetime
    visibility: Visibility = Visibility.PROJECT_SHARED
