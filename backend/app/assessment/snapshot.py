"""Building the evidence snapshot an assessment is made from (ASSESS-01, architecture §9.2).

The snapshot is the honest boundary of an assessment: it says exactly what was looked at, and
records what was left out and why. It is built from a student's own view of the evidence, because
the approved assessment is published to them and every citation in it has to open (QA-06).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.types import Role, Visibility
from app.evidence import service as evidence_service

log = logging.getLogger(__name__)

# Repository work merged inside the window but authored before it is included and flagged, so the
# assessment can tell integration apart from this week's work (REPO-06).
INTEGRATION_LAG = timedelta(days=14)


@dataclass(slots=True)
class SnapshotItem:
    evidence_ref_id: UUID
    text: str
    source_kind: Any
    source_id: UUID
    source_version: str
    locator: str
    visibility: Visibility
    source_time: datetime
    integration_of_earlier_work: bool = False


@dataclass(slots=True)
class SnapshotDraft:
    """What the builder found, before it is written down."""

    items: list[SnapshotItem] = field(default_factory=list)
    coverage_notes: dict[str, Any] = field(default_factory=dict)


def student_view(scope_owner_id: UUID, workspace_id: UUID, project_id: UUID, epoch: int) -> Scope:
    """The student's own scope, which is the only lens a snapshot is built through.

    Using the professor's scope here would let professor-only material into an assessment that is
    later published to the student (ASSESS-01, QA-06).
    """
    return Scope(
        workspace_id=workspace_id,
        user_id=scope_owner_id,
        role=Role.STUDENT,
        project_ids=frozenset({project_id}),
        access_epoch=epoch,
    )


async def collect(
    session: AsyncSession,
    *,
    scope: Scope,
    project_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> SnapshotDraft:
    """Gather everything in the window the student may see, and note what is missing."""
    draft = SnapshotDraft()

    hits = await evidence_service.search_evidence_window(
        session, scope, project_id=project_id, since=window_start, until=window_end
    )
    for hit in hits:
        draft.items.append(
            SnapshotItem(
                evidence_ref_id=hit.evidence_ref_id,
                text=hit.text,
                source_kind=hit.source_kind,
                source_id=hit.source_id,
                source_version=hit.source_version,
                locator=hit.locator,
                visibility=hit.visibility,
                source_time=hit.source_time,
            )
        )

    # Work merged this week but written earlier: real, and not this week's progress (REPO-06).
    earlier = await evidence_service.search_evidence_window(
        session,
        scope,
        project_id=project_id,
        since=window_start - INTEGRATION_LAG,
        until=window_start,
        merged_within=(window_start, window_end),
    )
    for hit in earlier:
        draft.items.append(
            SnapshotItem(
                evidence_ref_id=hit.evidence_ref_id,
                text=hit.text,
                source_kind=hit.source_kind,
                source_id=hit.source_id,
                source_version=hit.source_version,
                locator=hit.locator,
                visibility=hit.visibility,
                source_time=hit.source_time,
                integration_of_earlier_work=True,
            )
        )

    seen: set[UUID] = set()
    unique: list[SnapshotItem] = []
    for item in draft.items:
        if item.evidence_ref_id in seen:
            continue
        seen.add(item.evidence_ref_id)
        unique.append(item)
    draft.items = unique
    return draft
