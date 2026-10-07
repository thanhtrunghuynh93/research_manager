"""Queries over the evidence tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.ids import uuid7
from app.evidence.models import EvidenceChunk, EvidenceReference, EvidenceSourceKind


async def forget_sources(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_kind: EvidenceSourceKind,
    source_ids: tuple[UUID, ...],
) -> int:
    """Delete the references for these sources; their chunks cascade from the composite key."""
    if not source_ids:
        return 0
    result = await session.execute(
        delete(EvidenceReference)
        .where(
            EvidenceReference.workspace_id == workspace_id,
            EvidenceReference.source_kind == source_kind,
            EvidenceReference.source_id.in_(source_ids),
        )
        .returning(EvidenceReference.id)
    )
    return len(result.scalars().all())


async def upsert_evidence_reference(session: AsyncSession, **values: object) -> EvidenceReference:
    """One reference per (source kind, id, version): re-indexing updates rather than duplicates."""
    statement = (
        insert(EvidenceReference)
        .values(id=uuid7(), **values)
        .on_conflict_do_update(
            index_elements=["source_kind", "source_id", "source_version"],
            set_={
                "project_id": values.get("project_id"),
                "owner_student_id": values.get("owner_student_id"),
                "visibility": values.get("visibility"),
                "locator": values.get("locator"),
                "supported_claim": values.get("supported_claim"),
                "source_time": values.get("source_time"),
            },
        )
        .returning(EvidenceReference)
    )
    reference = (await session.execute(statement)).scalar_one()
    await session.flush()
    return reference


async def delete_chunks(session: AsyncSession, evidence_ref_id: UUID) -> None:
    await session.execute(
        delete(EvidenceChunk).where(EvidenceChunk.evidence_ref_id == evidence_ref_id)
    )


async def chunks_for_reference(session: AsyncSession, evidence_ref_id: UUID) -> list[EvidenceChunk]:
    return list(
        (
            await session.execute(
                select(EvidenceChunk)
                .where(EvidenceChunk.evidence_ref_id == evidence_ref_id)
                .order_by(EvidenceChunk.chunk_no)
            )
        )
        .scalars()
        .all()
    )


async def chunks_in_window(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID,
    since: datetime,
    until: datetime,
) -> list[tuple[EvidenceChunk, EvidenceReference]]:
    """Everything the caller may see in a window, for the snapshot builder (ASSESS-01)."""
    from app.evidence.index.retrieval import visible_chunks

    query = (
        select(EvidenceChunk, EvidenceReference)
        .join(EvidenceReference, EvidenceReference.id == EvidenceChunk.evidence_ref_id)
        .where(
            visible_chunks(scope),
            EvidenceChunk.project_id == project_id,
            EvidenceChunk.source_time >= since,
            EvidenceChunk.source_time < until,
        )
    )
    rows = await session.execute(query.order_by(EvidenceChunk.source_time, EvidenceChunk.chunk_no))
    return [(chunk, reference) for chunk, reference in rows]


async def chunks_for_sources(
    session: AsyncSession,
    scope: Scope,
    *,
    source_kind: EvidenceSourceKind,
    source_ids: list[UUID],
) -> list[tuple[EvidenceChunk, EvidenceReference]]:
    """Everything the caller may see that came from these sources, whatever their timestamps."""
    from app.evidence.index.retrieval import visible_chunks

    if not source_ids:
        return []
    rows = await session.execute(
        select(EvidenceChunk, EvidenceReference)
        .join(EvidenceReference, EvidenceReference.id == EvidenceChunk.evidence_ref_id)
        .where(
            visible_chunks(scope),
            EvidenceReference.source_kind == source_kind,
            EvidenceReference.source_id.in_(source_ids),
        )
        .order_by(EvidenceChunk.source_time, EvidenceChunk.chunk_no)
    )
    return [(chunk, reference) for chunk, reference in rows]


async def get_evidence_reference(
    session: AsyncSession, scope: Scope, reference_id: UUID
) -> EvidenceReference | None:
    return (
        await session.execute(
            select(EvidenceReference).where(
                EvidenceReference.id == reference_id, visible_to(scope, EvidenceReference)
            )
        )
    ).scalar_one_or_none()
