"""Search over the evidence index, and the other end of a citation (QA-02, QA-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ScopeDep, SessionDep
from app.evidence import service
from app.evidence.schemas import EvidenceReferenceOut

router = APIRouter(tags=["evidence"])


class EvidenceHitOut(BaseModel):
    evidence_ref_id: UUID
    text: str
    score: float
    source_kind: str
    source_id: UUID
    source_version: str
    locator: str
    project_id: UUID | None = None
    source_time: datetime


@router.get("/evidence/search", summary="Permission-filtered search over the evidence index")
async def search_evidence(
    scope: ScopeDep,
    session: SessionDep,
    q: Annotated[str, Field(min_length=1)],
    project_id: UUID | None = None,
    limit: int = 10,
) -> list[EvidenceHitOut]:
    """AUTH-02: the predicate sits inside each ranking arm, so a chunk outside the caller's scope
    is never scored and cannot surface through a snippet or a citation."""
    hits = await service.search_evidence(
        session, scope, query=q, project_id=project_id, limit=min(limit, 50)
    )
    return [
        EvidenceHitOut(
            evidence_ref_id=hit.evidence_ref_id,
            text=hit.text,
            score=hit.score,
            source_kind=str(hit.source_kind),
            source_id=hit.source_id,
            source_version=hit.source_version,
            locator=hit.locator,
            project_id=hit.project_id,
            source_time=hit.source_time,
        )
        for hit in hits
    ]


@router.get("/evidence/references/{reference_id}", summary="One citable evidence reference")
async def get_reference(
    reference_id: UUID, scope: ScopeDep, session: SessionDep
) -> EvidenceReferenceOut:
    return await service.get_reference(session, scope, reference_id)
