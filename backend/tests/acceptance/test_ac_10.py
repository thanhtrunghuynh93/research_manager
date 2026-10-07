"""AC-10 — The professor reviews six weeks of progress across a rubric change | The trajectory
labels each point with its rubric and marks the change; it does not present incompatible scores
as directly comparable.

Restated in 0.12: the professor reads the trajectory on a student's page (ASSESS-10, UI-04), not
in a chat answer. The trap is still a chart. Six numbers drawn on one line look like a trajectory
whether or not they mean the same thing, and a rubric change silently turns "this student
improved" into an artefact of reweighting. So `progress_series` — what GET /api/v1/trends serves —
carries the rubric version of every point, and the Trajectory component groups by it and states
the break (frontend: MyProfilePage.test.tsx, "rubric-break").
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.assessment.models import AssessmentReview, AssessmentVersion, ReviewState, RubricVersion
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance


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
    project, versions = await _six_weeks(db, prof_scope, student_a)

    series = await assessment_service.progress_series(
        db, prof_scope, student_id=student_a.id, project_id=project.id
    )

    assert [point.assessment_id for point in series] == [v.id for v in versions]  # type: ignore[attr-defined]
    assert all(point.rubric_version_id for point in series)
    rubrics = [point.rubric_version_id for point in series]
    assert len(set(rubrics)) == 2
    # One change, at the point where it happened: the break is between weeks three and four.
    assert rubrics[:3] == [rubrics[0]] * 3
    assert rubrics[3:] == [rubrics[3]] * 3


async def test_ac_10_each_index_is_computed_under_its_own_rubric(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """A point is never re-scored under whichever rubric is current: that would erase the break."""
    project, _versions = await _six_weeks(db, prof_scope, student_a)
    rubrics = {
        row.id: row.version
        for row in (
            await db.execute(
                RubricVersion.__table__.select().where(
                    RubricVersion.workspace_id == prof_scope.workspace_id
                )
            )
        ).all()
    }

    series = await assessment_service.progress_series(
        db, prof_scope, student_id=student_a.id, project_id=project.id
    )

    assert [rubrics[point.rubric_version_id] for point in series] == [1, 1, 1, 2, 2, 2]


async def test_ac_10_a_single_rubric_series_has_no_break_to_label(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The warning must mean something, so it must not be on every trajectory."""
    project, _versions = await _six_weeks(db, prof_scope, student_a, reweight_after=None)

    series = await assessment_service.progress_series(
        db, prof_scope, student_id=student_a.id, project_id=project.id
    )

    assert len(series) == 6
    assert len({point.rubric_version_id for point in series}) == 1


async def test_ac_10_the_student_reads_the_same_series_with_the_same_labels(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The break matters as much to the person assessed as to the person assessing."""
    project, _versions = await _six_weeks(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    theirs = await assessment_service.progress_series(
        db, scope, student_id=student_a.id, project_id=project.id
    )
    ours = await assessment_service.progress_series(
        db, prof_scope, student_id=student_a.id, project_id=project.id
    )

    assert [(p.assessment_id, p.rubric_version_id) for p in theirs] == [
        (p.assessment_id, p.rubric_version_id) for p in ours
    ]
