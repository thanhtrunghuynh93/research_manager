"""AC-10 — The professor asks for six-week progress across a rubric change | Answer cites the
relevant weeks and labels the change; it does not present incompatible scores as directly
comparable.

The trap is a chart. Six numbers drawn on one line look like a trajectory whether or not they mean
the same thing, and a rubric change silently turns "this student improved" into an artefact of
reweighting. So the series carries the rubric version of every point, and the fact that computes it
says plainly when more than one is present.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import RoutePlan
from app.assessment import service as assessment_service
from app.assessment.models import AssessmentReview, AssessmentVersion, ReviewState, RubricVersion
from app.assistant import facts
from app.assistant import service as assistant_service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

AS_OF = datetime(2026, 10, 26, tzinfo=UTC)


async def _six_weeks(
    db: AsyncSession,
    prof_scope: Scope,
    student: identity_models.User,
    *,
    reweight_after: int | None = 3,
) -> tuple[object, list[object]]:
    """Six approved weeks, optionally with the rubric reweighted partway through.

    `reweight_after=None` gives one rubric throughout, which is the control: a caveat that appears
    on every answer tells the professor nothing.
    """
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
    periods = await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 10, 25))
    assert len(periods) >= 6

    first_rubric = await assessment_service.ensure_rubric(db, prof_scope)
    # The professor reweights mid-term: the same ratings now produce a different index, which is
    # exactly why the two halves are not one series (ASSESS-09).
    second_rubric = RubricVersion(
        workspace_id=prof_scope.workspace_id,
        version=2,
        name="Reweighted rubric",
        dimensions={
            "progress": {"weight": 50},
            "learning": {"weight": 20},
            "rigor": {"weight": 20},
            "artifacts": {"weight": 10},
        },
        stage_applicability={},
        calculation_rules={},
        created_by=prof_scope.user_id,
    )
    db.add(second_rubric)
    await db.flush()

    created = []
    for index, period in enumerate(periods[:6]):
        rubric = first_rubric if reweight_after is None or index < reweight_after else second_rubric
        version = AssessmentVersion(
            workspace_id=prof_scope.workspace_id,
            student_id=student.id,
            project_id=project.id,
            period_id=period.id,
            version_no=1,
            rubric_version_id=rubric.id,
            ratings={},
            progress_index=60 + index * 5,
            coverage_pct=100,
            confidence="high",
            confidence_reasons=[],
            narrative={},
            # Dated to the week it assessed, so a six-week window actually contains them.
            created_at=datetime.combine(period.local_end, datetime.min.time(), tzinfo=UTC),
        )
        db.add(version)
        await db.flush()
        db.add(
            AssessmentReview(
                workspace_id=prof_scope.workspace_id,
                assessment_version_id=version.id,
                state=ReviewState.APPROVED,
                reviewer_id=prof_scope.user_id,
                published_at=datetime(2026, 9, 21, tzinfo=UTC),
            )
        )
        created.append(version)
    await db.flush()
    return project, created


async def test_ac_10_every_point_carries_the_rubric_that_produced_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project, _versions = await _six_weeks(db, prof_scope, student_a)

    fact = await facts.run(
        db,
        "progress_series",
        facts.FactQuery(
            scope=prof_scope, as_of=AS_OF, student_id=student_a.id, project_id=project.id
        ),
    )

    assert fact is not None
    assert fact.value == 6
    assert all(row["rubric_version_id"] for row in fact.rows)
    assert len({row["rubric_version_id"] for row in fact.rows}) == 2


async def test_ac_10_the_series_says_the_change_is_a_break_not_a_rise(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project, _versions = await _six_weeks(db, prof_scope, student_a)

    fact = await facts.run(
        db,
        "progress_series",
        facts.FactQuery(
            scope=prof_scope, as_of=AS_OF, student_id=student_a.id, project_id=project.id
        ),
    )

    assert fact is not None
    assert "not directly comparable" in fact.note
    assert "break" in fact.note


async def test_ac_10_a_single_rubric_series_is_labelled_comparable(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The warning must mean something, so it must not be on every answer."""
    project, _versions = await _six_weeks(db, prof_scope, student_a, reweight_after=None)

    fact = await facts.run(
        db,
        "progress_series",
        facts.FactQuery(
            scope=prof_scope, as_of=AS_OF, student_id=student_a.id, project_id=project.id
        ),
    )

    assert fact is not None
    assert "not directly comparable" not in fact.note
    assert "comparable" in fact.note


async def test_ac_10_the_answer_carries_the_series_and_its_caveat(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The caveat has to reach the professor, not just sit in a column."""
    project, _versions = await _six_weeks(db, prof_scope, student_a)

    answer = await assistant_service.ask(
        db,
        prof_scope,
        question="How has this student progressed over the last six weeks?",
        student_id=student_a.id,
        project_id=project.id,
        as_of=AS_OF,
        gateway=FakeGateway(
            responses={
                "route_question": RoutePlan(intent="fact", fact_functions=["progress_series"])
            }
        ),
    )

    series = [fact for fact in answer.facts if fact.name == "progress_series"]
    assert series, "the trajectory question is answered from the series, not from prose"
    assert "not directly comparable" in series[0].note
    assert "not directly comparable" in answer.answer
    assert len({row["rubric_version_id"] for row in series[0].rows}) == 2
