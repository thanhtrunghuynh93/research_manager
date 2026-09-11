"""Hybrid retrieval: the permission filter is part of the query (architecture §5.7).

The scope predicate is applied inside each ranking arm, so a chunk outside the caller's scope is
never scored and cannot surface through a ranking, a snippet, or a citation (AUTH-02, QA-06).

Lexical rank and vector distance are combined with reciprocal rank fusion, which needs no shared
scale between the two and degrades gracefully when one arm returns nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence.models import EvidenceChunk, EvidenceReference

Mode = Literal["hybrid", "lexical", "semantic"]

RRF_K = 60  # the usual damping constant; a rank-1 hit scores 1/61 in each arm
CANDIDATES = 50


@dataclass(frozen=True, slots=True)
class Hit:
    chunk_id: UUID
    evidence_ref_id: UUID
    text: str
    score: float
    source_kind: object
    source_id: UUID
    source_version: str
    locator: str
    project_id: UUID | None
    source_time: datetime


def visible_chunks(scope: Scope) -> ColumnElement[bool]:
    """The one place a chunk becomes eligible to be scored.

    The professor sees every chunk in their workspace. A student sees material shared with a
    project they are currently on, and their own private material — never another student's, and
    never anything labelled professor-only (QA-06).
    """
    same_workspace: ColumnElement[bool] = EvidenceChunk.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        EvidenceChunk.visibility != Visibility.PROFESSOR_ONLY,
        or_(
            and_(
                EvidenceChunk.visibility == Visibility.PROJECT_SHARED,
                EvidenceChunk.project_id.in_(scope.project_ids),
            ),
            and_(
                EvidenceChunk.visibility == Visibility.STUDENT_PRIVATE,
                EvidenceChunk.owner_student_id == scope.user_id,
            ),
        ),
    )


def _scoped(
    scope: Scope,
    *,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [visible_chunks(scope)]
    if project_id is not None:
        filters.append(EvidenceChunk.project_id == project_id)
    if since is not None:
        filters.append(EvidenceChunk.source_time >= since)
    if until is not None:
        filters.append(EvidenceChunk.source_time <= until)
    return filters


def _lexical_arm(query: str, filters: list[ColumnElement[bool]], limit: int) -> Select[Any]:
    match = func.websearch_to_tsquery("simple", query)
    return (
        select(
            EvidenceChunk.id.label("chunk_id"),
            func.row_number()
            .over(order_by=func.ts_rank_cd(EvidenceChunk.tsv, match).desc())
            .label("rank"),
        )
        .where(*filters, EvidenceChunk.tsv.op("@@")(match))
        .limit(limit)
    )


def _semantic_arm(
    embedding: list[float], filters: list[ColumnElement[bool]], limit: int
) -> Select[Any]:
    distance = EvidenceChunk.embedding.cosine_distance(embedding)
    return (
        select(
            EvidenceChunk.id.label("chunk_id"),
            func.row_number().over(order_by=distance).label("rank"),
        )
        .where(*filters)
        .limit(limit)
    )


async def search(
    session: AsyncSession,
    scope: Scope,
    *,
    query: str,
    embedding: list[float] | None = None,
    mode: Mode = "hybrid",
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 10,
) -> list[Hit]:
    text = query.strip()
    if not text:
        return []

    filters = _scoped(scope, project_id=project_id, since=since, until=until)
    arms = []
    if mode in ("hybrid", "lexical"):
        arms.append(_lexical_arm(text, filters, CANDIDATES).subquery("lexical"))
    if mode in ("hybrid", "semantic") and embedding is not None:
        arms.append(_semantic_arm(embedding, filters, CANDIDATES).subquery("semantic"))
    if not arms:
        return []

    # Reciprocal rank fusion over the arms, each already permission-filtered.
    contributions = [
        select(
            arm.c.chunk_id.label("chunk_id"),
            (1.0 / (RRF_K + arm.c.rank)).label("score"),
        )
        for arm in arms
    ]
    fused: Any = contributions[0]
    for contribution in contributions[1:]:
        fused = fused.union_all(contribution)

    scores = fused.subquery("fused")
    totals = (
        select(scores.c.chunk_id, func.sum(scores.c.score).label("score"))
        .group_by(scores.c.chunk_id)
        .subquery("totals")
    )

    rows = await session.execute(
        select(
            EvidenceChunk.id,
            EvidenceChunk.evidence_ref_id,
            EvidenceChunk.text,
            totals.c.score,
            EvidenceReference.source_kind,
            EvidenceReference.source_id,
            EvidenceReference.source_version,
            EvidenceReference.locator,
            EvidenceChunk.project_id,
            EvidenceChunk.source_time,
        )
        .join(totals, totals.c.chunk_id == EvidenceChunk.id)
        .join(EvidenceReference, EvidenceReference.id == EvidenceChunk.evidence_ref_id)
        .where(*filters)
        .order_by(totals.c.score.desc(), EvidenceChunk.source_time.desc())
        .limit(limit)
    )

    return [
        Hit(
            chunk_id=row[0],
            evidence_ref_id=row[1],
            text=row[2],
            score=float(row[3]),
            source_kind=row[4],
            source_id=row[5],
            source_version=row[6],
            locator=row[7],
            project_id=row[8],
            source_time=row[9],
        )
        for row in rows
    ]
