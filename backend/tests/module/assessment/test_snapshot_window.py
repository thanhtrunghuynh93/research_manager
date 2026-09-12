"""ASSESS-01 and REPO-06: what a week's snapshot is allowed to contain.

Two ways the boundary was wrong, in opposite directions.

`merged_within` was accepted by `search_evidence_window` and never applied, so the second pass —
meant to pick up repository work written earlier and merged during the week — returned the whole
preceding fortnight. Every chunk of it had already been assessed in the week it belonged to, and
the flag distinguishing it was dropped before the rating step saw it, so last fortnight's work was
re-counted as this week's, three weeks running.

In the other direction, a report entry was only ever found by timestamp. A report submitted after
the deadline has a `submitted_at` past the window's end, so the student's own account of their
work fell out of the assessment of it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service, snapshot
from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models as evidence_models
from app.evidence import service as evidence_service
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _week(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[object, object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    repository = await evidence_service.connect_repository(
        db,
        prof_scope,
        provider="github",
        external_id=str(uuid4().int % 10_000_000),
        full_name="lab/baseline",
        connector=FakeRepositoryConnector(),
    )
    await evidence_service.link_project(db, prof_scope, repository.id, project.id)
    return period, project, repository


async def _repository_evidence(
    db: AsyncSession,
    prof_scope: Scope,
    project: object,
    repository: object,
    *,
    authored_at: datetime,
    merged_at: datetime | None,
    text: str,
) -> None:
    """A repository event and the chunk that cites it, with the two times set independently."""
    event = evidence_models.RepositoryEvent(
        workspace_id=prof_scope.workspace_id,
        repository_id=repository.id,
        provider_event_id=str(uuid4()),
        kind=evidence_models.EventKind.PR_MERGED,
        title=text,
        authored_at=authored_at,
        merged_at=merged_at,
        event_at=merged_at or authored_at,
    )
    db.add(event)
    await db.flush()

    await evidence_service.index_evidence(
        db,
        workspace_id=prof_scope.workspace_id,
        project_id=project.id,
        source_kind=evidence_models.EvidenceSourceKind.REPOSITORY_EVENT,
        source_id=event.id,
        source_version="1",
        locator="pull request",
        text=text,
        visibility=Visibility.PROJECT_SHARED,
        source_time=authored_at,
    )


async def test_earlier_work_is_included_only_when_it_was_merged_this_week(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, repository = await _week(db, prof_scope, student_a)
    start = period.start_utc

    await _repository_evidence(
        db,
        prof_scope,
        project,
        repository,
        authored_at=start - timedelta(days=9),
        merged_at=start + timedelta(days=1),
        text="The retrieval refactor, opened a week and a half ago and landed on Tuesday.",
    )
    # Same age, never merged into this week: already assessed where it belongs.
    await _repository_evidence(
        db,
        prof_scope,
        project,
        repository,
        authored_at=start - timedelta(days=9),
        merged_at=start - timedelta(days=8),
        text="The loader fix, opened and landed last fortnight.",
    )

    epoch = await identity_service.access_epoch(db, prof_scope.workspace_id)
    scope = snapshot.student_view(student_a.id, prof_scope.workspace_id, project.id, epoch)
    draft = await snapshot.collect(
        db,
        scope=scope,
        project_id=project.id,
        window_start=start,
        window_end=period.end_utc,
    )

    texts = [item.text for item in draft.items]
    assert any("landed on Tuesday" in text for text in texts)
    assert not any("last fortnight" in text for text in texts)


async def test_earlier_work_that_is_included_is_flagged_as_integration(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, repository = await _week(db, prof_scope, student_a)
    start = period.start_utc
    await _repository_evidence(
        db,
        prof_scope,
        project,
        repository,
        authored_at=start - timedelta(days=3),
        merged_at=start + timedelta(days=1),
        text="Opened before the week, merged during it.",
    )

    epoch = await identity_service.access_epoch(db, prof_scope.workspace_id)
    scope = snapshot.student_view(student_a.id, prof_scope.workspace_id, project.id, epoch)
    draft = await snapshot.collect(
        db,
        scope=scope,
        project_id=project.id,
        window_start=start,
        window_end=period.end_utc,
    )

    carried = [item for item in draft.items if "Opened before the week" in item.text]
    assert carried and carried[0].integration_of_earlier_work is True


async def test_the_rating_step_can_tell_integration_from_this_weeks_work(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The flag was recorded on the snapshot and then dropped on the way to the model."""
    period, project, repository = await _week(db, prof_scope, student_a)
    await _repository_evidence(
        db,
        prof_scope,
        project,
        repository,
        authored_at=period.start_utc - timedelta(days=3),
        merged_at=period.start_utc + timedelta(days=1),
        text="Opened before the week, merged during it.",
    )
    scope = await identity_service.scope_for(db, student_a)
    version = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Landed the refactor.",
                "results": "Merged.",
            }
        ],
    )

    seen: list[dict] = []

    class _Capturing(FakeGateway):
        async def complete_structured(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs["prompt_id"] == "rate_rubric":
                seen.append(kwargs["inputs"])
            return await super().complete_structured(**kwargs)

    await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=_Capturing(),
    )

    assert seen
    flags = {item["integration_of_earlier_work"] for item in seen[0]["evidence"]}
    assert flags == {True, False}, "both kinds reached the model, told apart"


async def test_a_late_report_is_still_in_its_own_weeks_snapshot(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A report belongs to the week it is about, not the week it was sent."""
    period, project, repository = await _week(db, prof_scope, student_a)
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
