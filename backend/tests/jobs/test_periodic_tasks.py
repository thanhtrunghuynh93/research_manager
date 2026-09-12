"""The scheduled work that makes the week happen without anybody asking (architecture §12).

Each of these exists because its absence is silent. Without `ensure_periods` the calendar stops
and nobody is told; without `freeze_baselines` commitment completion is unavailable for reasons
that look like a bug; without `queue_health` a worker that stopped polling looks like a quiet week.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import observability
from app.core.authz import Scope
from app.identity import models as identity_models
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _configured(db: AsyncSession, prof_scope: Scope, student: identity_models.User) -> object:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
    )
    return project


async def test_the_daily_task_materialises_periods_for_every_workspace(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _configured(db, prof_scope, student_a)

    created = await reporting_service.ensure_periods_everywhere(db)

    assert created > 0
    periods = await reporting_service.list_periods(db, prof_scope)
    assert periods
    # And obligations with them: a period nobody owes a report for is not a reporting week.
    assert await reporting_service.list_obligations(db, prof_scope, periods[0].id)


async def test_a_workspace_with_no_calendar_is_skipped_rather_than_failing(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The professor has not made that decision yet; a daily error about it would help nobody."""
    created = await reporting_service.ensure_periods_everywhere(db)

    assert created == 0


async def test_running_it_twice_creates_nothing_further(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _configured(db, prof_scope, student_a)
    await reporting_service.ensure_periods_everywhere(db)
    before = len(await reporting_service.list_periods(db, prof_scope))

    await reporting_service.ensure_periods_everywhere(db)

    assert len(await reporting_service.list_periods(db, prof_scope)) == before


async def test_baselines_are_frozen_once_a_period_has_opened(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """PROJ-04/AC-18: an empty baseline is still a baseline — it records that there was no plan."""
    await _configured(db, prof_scope, student_a)
    periods = await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    await reporting_service.ensure_obligations(db, prof_scope, periods[0].id)
    after_it_opened = periods[0].start_utc + timedelta(days=1)

    frozen = await reporting_service.freeze_due_baselines(db, at=after_it_opened)

    assert frozen >= 1


async def test_a_period_that_has_not_opened_yet_is_left_alone(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Freezing early would fix a plan the student can still legitimately change."""
    await _configured(db, prof_scope, student_a)
    periods = await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    await reporting_service.ensure_obligations(db, prof_scope, periods[0].id)

    frozen = await reporting_service.freeze_due_baselines(
        db, at=periods[0].start_utc - timedelta(days=1)
    )

    assert frozen == 0


async def test_freezing_twice_leaves_the_first_baseline_in_place(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Idempotent by construction, so the task can re-cover a period the worker was down for."""
    await _configured(db, prof_scope, student_a)
    periods = await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
    await reporting_service.ensure_obligations(db, prof_scope, periods[0].id)
    at = periods[0].start_utc + timedelta(days=1)
    first = await reporting_service.freeze_due_baselines(db, at=at)

    second = await reporting_service.freeze_due_baselines(db, at=at)

    assert first == second, "the same baselines, not a second set"


# ------------------------------------------------------------------ observability


async def test_refreshing_the_metrics_reads_every_section(db: AsyncSession) -> None:
    summary = await observability.refresh(db)

    assert set(summary) == {"queue", "sync", "assessment", "email"}


async def test_the_queue_gauges_are_populated_from_the_queue_tables(db: AsyncSession) -> None:
    """procrastinate owns those tables, so this is the one place they are read as SQL."""
    summary = await observability.refresh(db)

    assert "depth" in summary["queue"]
    assert summary["queue"]["oldest_seconds"] >= 0


async def test_a_failing_section_does_not_take_the_refresh_with_it(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monitoring that can break the thing it monitors is worse than no monitoring."""

    async def _explode(session: AsyncSession) -> dict[str, object]:
        raise RuntimeError("no such table")

    monkeypatch.setattr(observability, "_queue", _explode)

    summary = await observability.refresh(db)

    assert summary["queue"] == {}
    assert "assessment" in summary


async def test_the_metrics_endpoint_exposes_the_named_series(db: AsyncSession) -> None:
    """Requirements §11 observability: queue latency, sync staleness, model errors, citation
    validation failures, and access denials."""
    from prometheus_client import generate_latest

    await observability.refresh(db)
    exposed = generate_latest().decode()

    for series in (
        "rm_queue_depth",
        "rm_queue_oldest_seconds",
        "rm_sync_staleness_seconds",
        "rm_model_calls_total",
        "rm_citation_validation_failures_total",
        "rm_access_denials_total",
        "rm_review_queue",
    ):
        assert series in exposed


def test_no_metric_label_can_identify_a_person() -> None:
    """A metric is scraped into a system with different access rules from this one, so a student
    id in a label would be a disclosure through the monitoring stack."""
    from app.core import metrics

    for series in (
        metrics.MODEL_CALLS,
        metrics.CITATION_FAILURES,
        metrics.ACCESS_DENIALS,
        metrics.QUEUE_DEPTH,
        metrics.JOB_FAILURES,
        metrics.REPOSITORIES,
        metrics.ANALYSIS_RUNS,
        metrics.EMAIL_DELIVERIES,
    ):
        names = set(series._labelnames)  # noqa: SLF001 - the point of the test is the declaration
        assert not (names & {"student", "student_id", "user", "user_id", "email", "workspace_id"})


async def test_the_access_denial_counter_moves_when_a_request_is_refused(
    client: object, student_a: identity_models.User
) -> None:
    from prometheus_client import generate_latest

    from tests.factories import DEFAULT_PASSWORD

    await client.post(  # type: ignore[attr-defined]
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )
    before = generate_latest().decode()

    await client.get("/api/v1/overview")  # type: ignore[attr-defined]

    assert 'rm_access_denials_total{status="403"}' in generate_latest().decode()
    assert before != generate_latest().decode()
