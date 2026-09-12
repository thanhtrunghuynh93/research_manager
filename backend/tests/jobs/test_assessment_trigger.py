"""A submitted report has to produce a draft on its own (architecture §9.1, repo_layout §3.2).

This is the seam that makes the product run unattended. `reporting` emits `ReportSubmitted`,
`assessment` subscribes and enqueues one pipeline job per project entry whose content actually
moved, and the worker runs them. Without it the review queue stays empty until somebody remembers
to ask for each assessment by hand, which is not a product.

Two rules the enqueue itself has to keep. One job per *entry*, because AC-01 wants two separate
assessments from one weekly package; and none at all for an entry carried forward unchanged,
because AC-17 says revising one project must not re-assess another.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import events as assessment_events
from app.core.authz import Scope
from app.core.jobs import key
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the defers instead of reaching the queue: this is about what is asked for."""
    calls: list[dict[str, Any]] = []

    async def _defer(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(assessment_events, "defer_pipeline", _defer)
    return calls


async def _week(
    db: AsyncSession,
    prof_scope: Scope,
    student: identity_models.User,
    *,
    projects: int = 1,
) -> tuple[Any, list[Any]]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    created = []
    for index in range(projects):
        project = await projects_service.create_project(
            db, prof_scope, title=f"Project {index}", stage="implementation"
        )
        await projects_service.update_project(db, prof_scope, project.id, status="active")
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
        created.append(project)
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, created


def _entry(project: Any, work: str = "Ran the baseline.") -> dict[str, Any]:
    return {
        "project_id": project.id,
        "stage": "implementation",
        "work_performed": work,
        "results": "nDCG@10 is 0.412.",
    }


async def test_submitting_a_report_enqueues_an_assessment(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    enqueued: list[dict[str, Any]],
) -> None:
    period, projects = await _week(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    await reporting_service.submit_report(
        db, scope, period_id=period.id, entries=[_entry(projects[0])]
    )

    assert len(enqueued) == 1
    assert enqueued[0]["student_id"] == student_a.id
    assert enqueued[0]["project_id"] == projects[0].id
    assert enqueued[0]["period_id"] == period.id


async def test_a_package_with_two_projects_enqueues_two_assessments(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    enqueued: list[dict[str, Any]],
) -> None:
    """AC-01: one weekly package, two entries, two separate assessments."""
    period, projects = await _week(db, prof_scope, student_a, projects=2)
    scope = await identity_service.scope_for(db, student_a)

    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[_entry(projects[0]), _entry(projects[1])],
    )

    assert {call["project_id"] for call in enqueued} == {projects[0].id, projects[1].id}


async def test_a_resubmission_enqueues_only_the_entry_whose_content_moved(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    enqueued: list[dict[str, Any]],
) -> None:
    """AC-17: revising one project entry must not re-assess the other."""
    period, projects = await _week(db, prof_scope, student_a, projects=2)
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[_entry(projects[0]), _entry(projects[1])],
    )
    enqueued.clear()

    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            _entry(projects[0], work="Corrected: the parser was off by one."),
            _entry(projects[1]),  # byte-identical to the first submission
        ],
    )

    assert [call["project_id"] for call in enqueued] == [projects[0].id]


async def test_the_job_key_is_stable_so_a_retry_is_the_same_job(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Architecture §12: the queueing lock is what makes at-least-once delivery safe."""
    period, projects = await _week(db, prof_scope, student_a)

    first = assessment_events.pipeline_key(
        student_id=student_a.id,
        project_id=projects[0].id,
        period_id=period.id,
        report_version_id=period.id,
    )
    second = assessment_events.pipeline_key(
        student_id=student_a.id,
        project_id=projects[0].id,
        period_id=period.id,
        report_version_id=period.id,
    )

    assert first == second
    assert first.startswith(key("assess", student_a.id))


async def test_an_enqueue_failure_does_not_lose_the_report(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirements §10: report acceptance must not wait for anything downstream to be healthy.

    The queue is in the same database, so an enqueue failure here is exotic — but if it happens,
    the submitted version is what must survive, and the professor's retry endpoint exists for
    exactly this (AC-13).
    """

    async def _explode(**kwargs: Any) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(assessment_events, "defer_pipeline", _explode)
    period, projects = await _week(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    version = await reporting_service.submit_report(
        db, scope, period_id=period.id, entries=[_entry(projects[0])]
    )

    assert version.version_no == 1
    stored = await reporting_service.get_version(db, prof_scope, version.id)
    assert stored.entries[0].work_performed == "Ran the baseline."
