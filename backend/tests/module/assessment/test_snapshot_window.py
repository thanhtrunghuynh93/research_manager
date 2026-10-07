"""ASSESS-01: what a week's snapshot is allowed to contain.

Evidence is collected by its time inside the week's window, so last week's attachment, already
assessed in the week it belonged to, is not counted again.

A report entry is the exception, found by identity rather than by timestamp. A report submitted
after the deadline has a `submitted_at` past the window's end, so a window alone would leave the
student's own account of their work out of the assessment of it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service, snapshot
from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models as evidence_models
from app.evidence import service as evidence_service
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.reporting import service as reporting_service
from tests.factories import make_week

pytestmark = pytest.mark.module


async def _week(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[object, object]:
    week = await make_week(
        db, prof_scope, [student], title="Baseline evaluation", joined_on=date(2026, 9, 1)
    )
    return week.period, week.project


async def _attachment_evidence(
    db: AsyncSession, prof_scope: Scope, project: object, *, at: datetime, text: str
) -> None:
    await evidence_service.index_evidence(
        db,
        workspace_id=prof_scope.workspace_id,
        project_id=project.id,
        source_kind=evidence_models.EvidenceSourceKind.ARTIFACT_VERSION,
        source_id=uuid4(),
        source_version="1",
        locator="attachment",
        text=text,
        visibility=Visibility.PROJECT_SHARED,
        source_time=at,
    )


async def test_only_evidence_inside_the_window_is_collected(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, student_a)
    start = period.start_utc

    await _attachment_evidence(
        db, prof_scope, project, at=start + timedelta(days=1), text="The ablation table, Tuesday."
    )
    await _attachment_evidence(
        db, prof_scope, project, at=start - timedelta(days=8), text="The loader notes, last week."
    )

    scope = snapshot.student_view(student_a.id, prof_scope.workspace_id, project.id)
    draft = await snapshot.collect(
        db,
        scope=scope,
        project_id=project.id,
        window_start=start,
        window_end=period.end_utc,
    )

    texts = [item.text for item in draft.items]
    assert any("Tuesday" in text for text in texts)
    assert not any("last week" in text for text in texts)


async def test_a_late_report_is_still_in_its_own_weeks_snapshot(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A report belongs to the week it is about, not the week it was sent."""
    period, project = await _week(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the ablation and wrote it up.",
                "results": "No improvement, and the reason is now understood.",
            }
        ],
    )

    built = await service.build_snapshot(
        db, student_id=student_a.id, project_id=project.id, period_id=period.id
    )
    items = await service.snapshot_items(db, built.id)

    assert any("ablation" in item.text for item in items), (
        "the student's own account of the week is in the snapshot of it, "
        f"whether submitted_at ({datetime.now(UTC)}) fell inside the window or not"
    )
