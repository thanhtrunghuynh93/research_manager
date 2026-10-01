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
from app.reporting import service as reporting_service
from tests.factories import Week, make_entry, make_week, submit

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
    db: AsyncSession, prof_scope: Scope, student: identity_models.User, *, projects: int = 1
) -> Week:
    return await make_week(db, prof_scope, [student], projects=projects, joined_on=date(2026, 9, 1))


def _entry(project: Any, work: str = "Ran the baseline.") -> dict[str, Any]:
    return make_entry(project.id, work=work, results="nDCG@10 is 0.412.", next_plan={})


async def test_submitting_a_report_enqueues_an_assessment(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    enqueued: list[dict[str, Any]],
) -> None:
    week = await _week(db, prof_scope, student_a)
    period, projects = week.period, week.projects

    await submit(db, student_a, week, _entry(projects[0]))

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
    week = await _week(db, prof_scope, student_a, projects=2)
    projects = week.projects

    await submit(db, student_a, week, _entry(projects[0]), _entry(projects[1]))

    assert {call["project_id"] for call in enqueued} == {projects[0].id, projects[1].id}


async def test_a_resubmission_enqueues_only_the_entry_whose_content_moved(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    enqueued: list[dict[str, Any]],
) -> None:
    """AC-17: revising one project entry must not re-assess the other."""
    week = await _week(db, prof_scope, student_a, projects=2)
    projects = week.projects
    await submit(db, student_a, week, _entry(projects[0]), _entry(projects[1]))
    enqueued.clear()

    await submit(
        db,
        student_a,
        week,
        _entry(projects[0], work="Corrected: the parser was off by one."),
        _entry(projects[1]),  # byte-identical to the first submission
    )

    assert [call["project_id"] for call in enqueued] == [projects[0].id]


async def test_the_job_key_is_stable_so_a_retry_is_the_same_job(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Architecture §12: the queueing lock is what makes at-least-once delivery safe."""
    week = await _week(db, prof_scope, student_a)
    period, projects = week.period, week.projects

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
    week = await _week(db, prof_scope, student_a)
    projects = week.projects

    version = await submit(db, student_a, week, _entry(projects[0]))

    assert version.version_no == 1
    stored = await reporting_service.get_version(db, prof_scope, version.id)
    assert stored.entries[0].work_performed == "Ran the baseline."
