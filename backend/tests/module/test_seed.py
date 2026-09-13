"""The demo dataset (docs/repo_layout.md §6).

`make seed`, `scripts/seed_demo.py` and the deploy runbook all point at this command, so it has to
work. It is tested rather than eyeballed for a second reason: it runs every module's service in one
pass, which makes it an unusually good smoke test of the whole write path.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.core.errors import ConflictError
from app.evidence import service as evidence_service
from app.identity import service as identity_service
from app.identity.models import User
from app.reporting import service as reporting_service
from app.seed import PROF_EMAIL, load_demo

pytestmark = pytest.mark.module


async def test_the_demo_dataset_loads(db: AsyncSession) -> None:
    result = await load_demo(db)

    assert len(result.student_ids) == 6
    assert len(result.project_ids) == 4
    assert len(result.period_ids) >= 8
    assert result.reports >= 6
    assert result.assessments >= 1


async def test_loading_it_twice_is_refused_rather_than_duplicated(db: AsyncSession) -> None:
    """A second workspace with the same professor would be a confusing mess to unpick."""
    await load_demo(db)

    with pytest.raises(ConflictError):
        await load_demo(db)


async def test_a_student_sees_their_own_reports_and_nobody_else_s(db: AsyncSession) -> None:
    result = await load_demo(db)
    student = await db.get(User, result.student_ids[0])
    assert student is not None
    scope = await identity_service.scope_for(db, student)

    submissions = await reporting_service.submissions(db, scope)

    assert submissions
    assert {row.student_id for row in submissions} == {student.id}


async def test_the_professor_has_drafts_waiting_and_one_released_week(db: AsyncSession) -> None:
    """The demo should show the review workflow mid-flight, not an empty queue."""
    result = await load_demo(db)
    professor = await db.get(User, result.professor_id)
    assert professor is not None
    prof_scope = await identity_service.scope_for(db, professor)

    queue = await assessment_service.review_queue(db, prof_scope)
    student = await db.get(User, result.student_ids[0])
    assert student is not None
    released = await assessment_service.list_assessments(
        db, await identity_service.scope_for(db, student), student_id=student.id
    )

    assert queue, "the review queue should not be empty in the demo"
    assert released, "one week should already be released to the student"


async def test_the_repository_evidence_is_present_and_attributed(db: AsyncSession) -> None:
    """REPO-04/AC-06: joint work is joint, and merging is not authorship."""
    result = await load_demo(db)
    professor = await db.get(User, result.professor_id)
    assert professor is not None
    prof_scope = await identity_service.scope_for(db, professor)

    repositories = await evidence_service.list_repositories(db, prof_scope)
    assert repositories
    contributions = await evidence_service.list_contributions(
        db, prof_scope, project_id=result.project_ids[0]
    )

    assert contributions
    # The co-authored commit produced joint rows rather than crediting one student with both.
    assert any(row.share == "joint" for row in contributions)
    # The merge is recorded as a merge. It is a contribution, and it is not authorship.
    assert any(row.role == "merger" for row in contributions)
    assert all(row.role != "merger" or row.share == "individual" for row in contributions)
    # AC-06: however many students share an artifact, the project counts it once.
    distinct = await evidence_service.distinct_event_count(
        db, prof_scope, project_id=result.project_ids[0]
    )
    assert distinct < len(contributions)


async def test_the_demo_includes_a_claim_the_evidence_cannot_support(db: AsyncSession) -> None:
    """AC-07: a demo that only contains the happy path teaches the wrong thing about this system."""
    result = await load_demo(db)
    professor = await db.get(User, result.professor_id)
    assert professor is not None
    prof_scope = await identity_service.scope_for(db, professor)

    assessments = await assessment_service.list_assessments(
        db, prof_scope, student_id=result.student_ids[0], project_id=result.project_ids[0]
    )

    assert any(assessment.confidence in ("medium", "low") for assessment in assessments), (
        "at least one week should be visibly uncertain"
    )


async def test_the_professor_can_sign_in_with_the_documented_password(db: AsyncSession) -> None:
    from app.seed import PASSWORD

    await load_demo(db)

    logged_in = await identity_service.login(db, email=PROF_EMAIL, password=PASSWORD)

    assert logged_in.user.email == PROF_EMAIL
