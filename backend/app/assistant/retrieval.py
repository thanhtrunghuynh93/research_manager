"""Scope-filtered retrieval for the assistant (QA-06, architecture §11).

This module adds almost nothing to `evidence.index.retrieval`, and that is the point: there is one
permission predicate and one ranking path, so an answer cannot reach material a search could not.
What it adds is the professor-only branch — supervision notes, which are deliberately not in the
index at all and are read through their own function, tagged, and never allowed into student-facing
text (QA-06, architecture §6.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.evidence import service as evidence_service

DEFAULT_LIMIT = 12


@dataclass(frozen=True, slots=True)
class Passage:
    """One retrieved piece of evidence, with the label that decides how it may be used."""

    evidence_ref_id: UUID
    text: str
    source_kind: str
    source_id: UUID
    source_version: str
    locator: str
    source_time: datetime
    # True for supervision notes: professor-only, and excluded from anything drafted for a student.
    private: bool = False

    @property
    def citation_id(self) -> str:
        return str(self.evidence_ref_id)


async def retrieve(
    session: AsyncSession,
    scope: Scope,
    *,
    query: str,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    include_private: bool = False,
) -> list[Passage]:
    """Evidence the caller may see, ranked, with private notes only on the professor's branch."""
    if not query.strip():
        return []

    hits = await evidence_service.search_evidence(
        session,
        scope,
        query=query,
        project_id=project_id,
        since=since,
        until=until,
        limit=limit,
    )
    passages = [
        Passage(
            evidence_ref_id=hit.evidence_ref_id,
            text=hit.text,
            source_kind=str(hit.source_kind),
            source_id=hit.source_id,
            source_version=hit.source_version,
            locator=hit.locator,
            source_time=hit.source_time,
        )
        for hit in hits
    ]

    if include_private and scope.is_prof:
        passages.extend(
            await _supervision_notes(
                session, scope, project_id=project_id, since=since, until=until
            )
        )
    return passages


async def _supervision_notes(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[Passage]:
    """QA-06: never indexed, never in a snapshot, and never in anything a student can read."""
    notes = await assessment_service.list_supervision_notes(
        session, scope, project_id=project_id, since=since, until=until
    )
    return [
        Passage(
            evidence_ref_id=note.id,
            text=note.body,
            source_kind="supervision_note",
            source_id=note.id,
            source_version="",
            locator=f"/students/{note.student_id}#notes",
            source_time=note.created_at,
            private=True,
        )
        for note in notes
    ]


def student_safe(passages: list[Passage]) -> list[Passage]:
    """Everything a student-facing draft may rest on. The filter is structural, not a prompt."""
    return [passage for passage in passages if not passage.private]
