"""The overview's numbers (UI-01, REP-08, AC-15).

Every number the professor acts on is computed from the tables at a stated instant. A count that
is sometimes right is the failure mode that looks like success, so these pin the rules that make
it right: excused and extended obligations are not missing, the deadline carries its timezone, and
every row names the person it is about.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.overview import service
from app.reporting import service as reporting_service
from tests.factories import make_week
from tests.module.overview.conftest import AFTER_THE_WEEK, submit_entry

pytestmark = [pytest.mark.module, pytest.mark.usefixtures("one_week_open")]


# ------------------------------------------------------------------ AC-15


async def test_ac_15_missing_reports_counts_obligations_not_impressions(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    week = await make_week(db, prof_scope, [student_a, student_b])
    await submit_entry(db, student_a, week)

    missing = await service.missing_reports(db, prof_scope, as_of=AFTER_THE_WEEK)

    assert missing is not None
    assert [row["student_id"] for row in missing] == [str(student_b.id)]
    assert missing[0]["student_name"] == student_b.display_name
    assert missing[0]["project_title"] == week.project.title


async def test_ac_15_an_excused_obligation_is_not_a_missing_report(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """AC-08: an approved exception changes the obligation; it must not read as a missed week."""
    week = await make_week(db, prof_scope, [student_a, student_b])
    await submit_entry(db, student_a, week)
    obligations = await reporting_service.list_obligations(
        db, prof_scope, week.period.id, student_id=student_b.id
    )
    await reporting_service.excuse_obligation(
        db, prof_scope, obligations[0].id, reason="approved leave"
    )

    assert await service.missing_reports(db, prof_scope, as_of=AFTER_THE_WEEK) == []


async def test_ac_15_an_extension_that_has_not_run_out_is_not_a_missing_report(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await make_week(db, prof_scope, [student_a])
    obligations = await reporting_service.list_obligations(
        db, prof_scope, week.period.id, student_id=student_a.id
    )
    await reporting_service.extend_obligation(
        db,
        prof_scope,
        obligations[0].id,
        until=AFTER_THE_WEEK + timedelta(days=2),
        reason="conference travel",
    )

    assert await service.missing_reports(db, prof_scope, as_of=AFTER_THE_WEEK) == []


async def test_a_workspace_with_no_week_has_nothing_to_count(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """None, not an empty list: the overview shows no note rather than "0 missing"."""
    assert await service.missing_reports(db, prof_scope, as_of=AFTER_THE_WEEK) is None


# ------------------------------------------------------------------ the deadline


async def test_the_next_deadline_names_the_timezone_it_is_expressed_in(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-01: 23:59 local is only meaningful with the locality attached."""
    week = await make_week(db, prof_scope, [student_a])

    deadline = await service.next_deadline(db, prof_scope, as_of=datetime(2026, 9, 15, tzinfo=UTC))

    assert deadline is not None
    assert deadline["period_id"] == str(week.period.id)
    assert deadline["timezone"] == "Asia/Ho_Chi_Minh"
    assert deadline["deadline_utc"] == week.period.deadline_utc.isoformat()


async def test_there_is_no_next_deadline_once_every_week_has_passed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await make_week(db, prof_scope, [student_a])

    assert await service.next_deadline(db, prof_scope, as_of=AFTER_THE_WEEK) is None


# ------------------------------------------------------------------ the week


async def test_the_week_lists_one_row_per_student_in_each_of_three_states(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    week = await make_week(db, prof_scope, [student_a, student_b])
    await submit_entry(db, student_a, week)

    rows = await service.week_reports(db, prof_scope, as_of=AFTER_THE_WEEK)

    states = {row["student_name"]: row["state"] for row in rows}
    assert states == {student_a.display_name: "submitted", student_b.display_name: "owed"}
    assert {row["period_id"] for row in rows} == {str(week.period.id)}


# ------------------------------------------------------------------ the review queue


async def test_a_draft_in_the_review_queue_names_its_student_and_project(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Without names, UUIDv7 drafts sharing a timestamp prefix were indistinguishable."""
    week = await make_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, week)
    draft = await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=week.project.id,
        period_id=week.period.id,
        gateway=FakeGateway(),
    )
    assert draft is not None

    # `created_at` is the database's own clock, which the frozen one does not reach.
    queue = await service.review_queue(db, prof_scope, as_of=datetime(2100, 1, 1, tzinfo=UTC))

    assert [row["assessment_id"] for row in queue] == [str(draft.id)]
    assert queue[0]["student_name"] == student_a.display_name
    assert queue[0]["project_title"] == week.project.title
