"""AC-15 — The professor reads the number of missing reports on the overview | The count matches
structured obligations after exemptions and deadline rules, with an explicit as-of time.

Restated in 0.12: the number is read on the overview (UI-01), not asked of a chat assistant. The
failure this guards against is still quiet — a count that is often right and cannot say when it
was true. So the obligations table is read at the instant the overview is served, and that instant
is part of the response.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.reporting import service as reporting_service
from tests.factories import Week, login, make_entry, make_week, submit

pytestmark = pytest.mark.acceptance

AFTER_THE_DEADLINE = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _one_week_open(monkeypatch: pytest.MonkeyPatch, frozen_now: Callable[[datetime], None]) -> None:
    """The world these tests describe: the week of 14 September is the only one open.

    Saving a calendar opens the weeks ahead of today, as the nightly job always has. Left to the
    wall clock that opened the week of the 21st too, and the overview then counted the week just
    begun instead of the one whose deadline had passed. What is under test is the
    arithmetic on one week's obligations, so the clock is pinned inside that week and nothing is
    opened past it.
    """
    frozen_now(datetime(2026, 9, 15, 3, 0, tzinfo=UTC))
    monkeypatch.setattr("app.reporting.service.DEFAULT_HORIZON", timedelta(0), raising=True)


async def _week(db: AsyncSession, prof_scope: Scope, students: list[identity_models.User]) -> Week:
    return await make_week(
        db, prof_scope, students, title="Retrieval baselines", joined_on=date(2026, 9, 1)
    )


async def _submit(db: AsyncSession, student: identity_models.User, week: Week) -> None:
    entry = make_entry(
        week.project.id, work="Ran the baseline.", results="nDCG@10 is 0.412.", next_plan={}
    )
    await submit(db, student, week, entry)


async def _outstanding(
    client: AsyncClient, prof: identity_models.User, frozen_now: Callable[[datetime], None]
) -> dict[str, object]:
    """The overview's outstanding section, read just after the deadline has passed."""
    frozen_now(AFTER_THE_DEADLINE)
    await login(client, prof)
    response = await client.get("/api/v1/overview")
    assert response.status_code == 200
    outstanding: dict[str, object] = response.json()["outstanding"]
    return outstanding


async def test_ac_15_the_count_comes_from_the_obligations(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    week = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, week)

    outstanding = await _outstanding(client, prof, frozen_now)

    assert outstanding["count"] == 1
    entries = outstanding["entries"]
    assert isinstance(entries, list)
    assert [entry["student_id"] for entry in entries] == [str(student_b.id)]


async def test_ac_15_the_count_states_the_instant_it_was_true(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    """Without an as-of, "one missing" is not a fact — it is a fact about a moment nobody named."""
    week = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, week)

    outstanding = await _outstanding(client, prof, frozen_now)

    # The pinned clock ticks forward from where it was set, as a real one would.
    as_of = datetime.fromisoformat(str(outstanding["as_of"]))
    assert AFTER_THE_DEADLINE <= as_of < AFTER_THE_DEADLINE + timedelta(minutes=1)


async def test_ac_15_an_exemption_and_an_extension_both_reduce_the_count(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    """AC-08: an approved exception must not surface as a missed report."""
    week = await _week(db, prof_scope, [student_a, student_b])
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    for obligation in obligations:
        if obligation.student_id == student_a.id:
            await reporting_service.excuse_obligation(
                db, prof_scope, obligation.id, reason="approved leave"
            )
        else:
            await reporting_service.extend_obligation(
                db,
                prof_scope,
                obligation.id,
                until=AFTER_THE_DEADLINE + timedelta(days=2),
                reason="conference travel",
            )

    outstanding = await _outstanding(client, prof, frozen_now)

    assert outstanding["count"] == 0
    assert "exemptions and extensions" in str(outstanding["note"])


async def test_ac_15_a_submission_just_before_the_deadline_is_not_missing(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
    frozen_now: Callable[[datetime], None],
) -> None:
    """The obligation is evaluated at the instant the overview is served."""
    week = await _week(db, prof_scope, [student_a])
    await _submit(db, student_a, week)

    outstanding = await _outstanding(client, prof, frozen_now)

    assert outstanding["count"] == 0
