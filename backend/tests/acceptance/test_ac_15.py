"""AC-15 — The professor asks for the number of missing reports | The answer matches structured
obligations after exemptions and deadline rules, with an explicit as-of time.

The failure this guards against is quiet. A language model handed a week of reports will produce a
number, and it will often be the right one, and there is no way to tell from the answer which time
it was. So the number never passes through the model: the obligations table is read at a stated
instant and the result is rendered.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import AnswerDraft, RoutePlan
from app.assistant import service as assistant_service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

AFTER_THE_DEADLINE = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
QUESTION = "How many reports are missing this week?"


@pytest.fixture(autouse=True)
def _one_week_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The world these tests describe: the week of 14 September is the only one open.

    Saving a calendar opens the weeks ahead of today, as the nightly job always has. Left to the
    wall clock that opened the week of the 21st too, and `missing_reports` then answered for the
    week just begun instead of the one whose deadline had passed. What is under test is the
    arithmetic on one week's obligations, so the clock is pinned inside that week and nothing is
    opened past it.
    """
    monkeypatch.setattr(
        "app.reporting.service.now", lambda: datetime(2026, 9, 15, 3, 0, tzinfo=UTC), raising=True
    )
    monkeypatch.setattr("app.reporting.service.DEFAULT_HORIZON", timedelta(0), raising=True)


async def _week(
    db: AsyncSession, prof_scope: Scope, students: list[identity_models.User]
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
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in students:
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def _submit(
    db: AsyncSession, student: identity_models.User, period: object, project: object
) -> None:
    scope = await identity_service.scope_for(db, student)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,  # type: ignore[attr-defined]
        entries=[
            {
                "project_id": project.id,  # type: ignore[attr-defined]
                "stage": "implementation",
                "work_performed": "Ran the baseline.",
                "results": "nDCG@10 is 0.412.",
            }
        ],
    )


def _misleading_gateway() -> FakeGateway:
    """Scripted to answer with the wrong number.

    A test that passes with this in place has proved the generation step was not consulted.
    """
    return FakeGateway(
        responses={
            "route_question": RoutePlan(intent="fact", fact_functions=["missing_reports"]),
            "answer": AnswerDraft(answer="Seven reports are missing."),
        }
    )


async def test_ac_15_the_count_comes_from_the_obligations_not_from_the_model(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    period, project = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, period, project)

    answer = await assistant_service.ask(
        db, prof_scope, question=QUESTION, as_of=AFTER_THE_DEADLINE, gateway=_misleading_gateway()
    )

    assert "Seven" not in answer.answer
    fact = next(fact for fact in answer.facts if fact.name == "missing_reports")
    assert fact.value == 1
    assert fact.rows[0]["student_id"] == str(student_b.id)


async def test_ac_15_the_answer_states_the_instant_the_count_was_true(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """Without an as-of, "one missing" is not a fact — it is a fact about a moment nobody named."""
    period, project = await _week(db, prof_scope, [student_a, student_b])
    await _submit(db, student_a, period, project)

    answer = await assistant_service.ask(
        db, prof_scope, question=QUESTION, as_of=AFTER_THE_DEADLINE, gateway=_misleading_gateway()
    )

    fact = next(fact for fact in answer.facts if fact.name == "missing_reports")
    assert fact.as_of == AFTER_THE_DEADLINE
    assert AFTER_THE_DEADLINE.isoformat() in answer.answer
    assert answer.time_range


async def test_ac_15_an_exemption_and_an_extension_both_reduce_the_count(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """AC-08: an approved exception must not surface as a missed report."""
    period, project = await _week(db, prof_scope, [student_a, student_b])
    obligations = await reporting_service.list_obligations(db, prof_scope, period.id)
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

    answer = await assistant_service.ask(
        db, prof_scope, question=QUESTION, as_of=AFTER_THE_DEADLINE, gateway=_misleading_gateway()
    )

    fact = next(fact for fact in answer.facts if fact.name == "missing_reports")
    assert fact.value == 0
    assert "exemptions and extensions" in fact.note


async def test_ac_15_a_submission_just_before_the_deadline_is_not_missing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The obligation is evaluated at the instant asked about, not when the period was created."""
    period, project = await _week(db, prof_scope, [student_a])
    await _submit(db, student_a, period, project)

    answer = await assistant_service.ask(
        db, prof_scope, question=QUESTION, as_of=AFTER_THE_DEADLINE, gateway=_misleading_gateway()
    )

    fact = next(fact for fact in answer.facts if fact.name == "missing_reports")
    assert fact.value == 0
