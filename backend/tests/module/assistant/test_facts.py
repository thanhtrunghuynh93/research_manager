"""The deterministic half of the assistant (QA-02, AC-15).

Every number the professor might act on is computed here, in SQL, through the same permission
predicate every other read uses. A model asked to count will sometimes be right; these tests exist
because "sometimes right" is the failure mode that looks like success.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import facts
from app.core.authz import Scope
from app.core.clock import now
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module

# The instant these questions are asked from: after the reporting week the fixtures build, and
# after whatever the clock says now, because the submissions in each test are written at the real
# current time. Pinned to a date, this was a time bomb — it was 2026-09-21T03:00Z, and on the
# morning of 21 September the clock passed it, so `submitted_at <= as_of` began excluding the
# test's own submissions and `timing_counts` answered with nothing.
AFTER_THE_WEEK = max(datetime(2026, 9, 21, 3, 0, tzinfo=UTC), now() + timedelta(hours=1))


@pytest.fixture(autouse=True)
def _one_week_open(monkeypatch: pytest.MonkeyPatch) -> None:
    # Saving a calendar opens the weeks ahead of the reporting clock. Pinned inside the week of
    # 14 September with no horizon, that week is the only one open — the world these helpers
    # describe. Left to the wall clock, the week of the 21st opened too and became "this week".
    monkeypatch.setattr(
        "app.reporting.service.now", lambda: datetime(2026, 9, 15, 3, 0, tzinfo=UTC), raising=True
    )
    monkeypatch.setattr("app.reporting.service.DEFAULT_HORIZON", timedelta(0), raising=True)


async def _week(
    db: AsyncSession,
    prof_scope: Scope,
    students: list[identity_models.User],
    *,
    title: str = "Retrieval baselines",
) -> tuple[object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title=title, stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in students:
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


def _query(scope: Scope, **kwargs: object) -> facts.FactQuery:
    return facts.FactQuery(scope=scope, as_of=AFTER_THE_WEEK, **kwargs)  # type: ignore[arg-type]


async def _submit(
    db: AsyncSession, student: identity_models.User, period: object, project: object, **fields: str
) -> object:
    scope = await identity_service.scope_for(db, student)
    return await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,  # type: ignore[attr-defined]
        entries=[
            {
                "project_id": project.id,  # type: ignore[attr-defined]
                "stage": "implementation",
                "work_performed": fields.get("work_performed", "Ran the baseline."),
                "results": fields.get("results", "nDCG@10 is 0.412."),
                "deviations": fields.get("deviations", ""),
                "questions": fields.get("questions", ""),
            }
        ],
    )


# ------------------------------------------------------------------ the registry


async def test_the_registry_names_every_function_the_router_may_call() -> None:
    names = facts.available()

    assert {"missing_reports", "next_deadline", "timing_counts", "members", "review_queue"} <= set(
        names
    )


async def test_an_invented_function_name_is_dropped_rather_than_approximated(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The router is a model. A near-match would answer a different question than the one asked."""
    assert facts.get("count_all_the_things") is None
    assert await facts.run(db, "count_all_the_things", _query(prof_scope)) is None


# ------------------------------------------------------------------ AC-15


async def test_ac_15_missing_reports_counts_obligations_not_impressions(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    period, project = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, period, project)

    fact = await facts.run(db, "missing_reports", _query(prof_scope, period_id=period.id))

    assert fact is not None
    assert fact.value == 1
    assert fact.rows[0]["student_id"] == str(student_b.id)
    assert fact.as_of == AFTER_THE_WEEK


async def test_ac_15_an_excused_obligation_is_not_a_missing_report(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """AC-08: an approved exception changes the obligation; it must not read as a missed week."""
    period, project = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, period, project)
    obligations = await reporting_service.list_obligations(
        db, prof_scope, period.id, student_id=student_b.id
    )
    await reporting_service.excuse_obligation(
        db, prof_scope, obligations[0].id, reason="approved leave"
    )

    fact = await facts.run(db, "missing_reports", _query(prof_scope, period_id=period.id))

    assert fact is not None and fact.value == 0


async def test_ac_15_an_extension_that_has_not_run_out_is_not_a_missing_report(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, [student_a])
    obligations = await reporting_service.list_obligations(
        db, prof_scope, period.id, student_id=student_a.id
    )
    await reporting_service.extend_obligation(
        db,
        prof_scope,
        obligations[0].id,
        until=AFTER_THE_WEEK + timedelta(days=2),
        reason="conference travel",
    )

    fact = await facts.run(db, "missing_reports", _query(prof_scope, period_id=period.id))

    assert fact is not None and fact.value == 0


async def test_a_student_asking_which_reports_are_missing_sees_only_their_own(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """AUTH-02: the fact function compiles the same predicate as every other read."""
    period, _project = await _week(db, prof_scope, [student_a, student_b])
    scope = await identity_service.scope_for(db, student_a)

    fact = await facts.run(db, "missing_reports", _query(scope, period_id=period.id))

    assert fact is not None
    assert fact.value == 1
    assert {row["student_id"] for row in fact.rows} == {str(student_a.id)}


# ------------------------------------------------------------------ deadlines and timing


async def test_the_next_deadline_names_the_timezone_it_is_expressed_in(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-01: 23:59 local is only meaningful with the locality attached."""
    await _week(db, prof_scope, [student_a])

    fact = await facts.run(
        db,
        "next_deadline",
        facts.FactQuery(scope=prof_scope, as_of=datetime(2026, 9, 15, tzinfo=UTC)),
    )

    assert fact is not None
    assert fact.rows[0]["timezone"] == "Asia/Ho_Chi_Minh"
    assert "23:59" in fact.note


async def test_timing_counts_read_the_first_submission_not_the_latest(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-07/AC-13: a revision must not relabel a late report as on time."""
    period, project = await _week(db, prof_scope, [student_a])
    await _submit(db, student_a, period, project)
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Revised after feedback.",
                "results": "Same numbers.",
            }
        ],
    )

    fact = await facts.run(db, "timing_counts", _query(prof_scope, student_id=student_a.id))

    assert fact is not None
    assert sum(fact.value.values()) == 1, "two versions of one report are one submission"


# ------------------------------------------------------------------ membership as of a date


async def test_membership_is_answered_at_an_instant_because_left_on_is_exclusive(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """PROJ-02/AUTH-03: a student removed today is not a member today."""
    _period, project = await _week(db, prof_scope, [student_a])
    memberships = await projects_service.list_members(db, prof_scope, project.id)
    await projects_service.end_membership(
        db, prof_scope, memberships[0].id, left_on=date(2026, 9, 18)
    )

    before = await facts.run(
        db,
        "members",
        facts.FactQuery(
            scope=prof_scope, as_of=datetime(2026, 9, 17, tzinfo=UTC), project_id=project.id
        ),
    )
    after = await facts.run(
        db,
        "members",
        facts.FactQuery(
            scope=prof_scope, as_of=datetime(2026, 9, 18, tzinfo=UTC), project_id=project.id
        ),
    )

    assert before is not None and before.value == 1
    assert after is not None and after.value == 0


# ------------------------------------------------------------------ blockers and freshness


async def test_blockers_are_quoted_from_the_entry_and_carry_a_citation(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, [student_a])
    await _submit(
        db,
        student_a,
        period,
        project,
        deviations="The cluster queue has been full since Tuesday.",
    )

    fact = await facts.run(db, "blockers", _query(prof_scope, student_id=student_a.id))

    assert fact is not None
    assert fact.value == 1
    assert "cluster queue" in fact.rows[0]["deviations"]
    assert fact.citations[0].source_kind == "report_entry"
    assert "report" in fact.note.lower()


async def test_a_workspace_with_no_repository_reports_no_stale_ones(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """REPO-01: the product is fully usable without a repository, this answer included."""
    fact = await facts.run(db, "stale_repositories", _query(prof_scope))

    assert fact is not None and fact.value == 0


async def test_the_review_queue_of_a_student_is_empty_by_construction(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await _week(db, prof_scope, [student_a])
    scope = await identity_service.scope_for(db, student_a)

    fact = await facts.run(db, "review_queue", _query(scope))

    assert fact is not None and fact.value == 0


# ---------------------------------------------------------------- a source its reader can open
#
# The two roles read a report through different routes. Every fact emitted the student's, so a
# professor following a source was redirected off a route their role cannot open, and the missing
# record and the wrong link looked the same from the outside (QA-03).


async def test_a_professors_report_citation_opens_that_students_week(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    period, project = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, period, project)

    fact = await facts.run(db, "missing_reports", _query(prof_scope, period_id=period.id))

    assert fact is not None
    assert [citation.locator for citation in fact.citations] == [
        f"/students/{student_b.id}/reports/{period.id}"
    ], "one source per student who owes, on the route a professor may open"
    assert fact.citations[0].label.startswith(student_b.display_name), "and named for them"
    assert fact.citations[0].label.endswith(f"week of {period.local_start} to {period.local_end}")


async def test_a_students_own_report_citation_stays_on_their_own_route(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _week(db, prof_scope, [student_a])
    await _submit(
        db,
        student_a,
        period,
        project,
        deviations="The cluster queue has been full since Tuesday.",
    )
    scope = await identity_service.scope_for(db, student_a)

    fact = await facts.run(db, "blockers", _query(scope, student_id=student_a.id))

    assert fact is not None
    assert fact.citations[0].locator == f"/report/{period.id}#{project.id}"


async def test_one_week_yields_one_source_per_student_rather_than_one_for_all(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """A week-level source pointed everybody at one place, and only one of them could use it."""
    period, _ = await _week(db, prof_scope, [student_a, student_b])

    fact = await facts.run(db, "week_reports", _query(prof_scope, period_id=period.id))

    assert fact is not None
    locators = {citation.locator for citation in fact.citations}
    assert locators == {
        f"/students/{student_a.id}/reports/{period.id}",
        f"/students/{student_b.id}/reports/{period.id}",
    }
