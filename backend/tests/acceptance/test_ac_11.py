"""AC-11 — A student's membership is removed after an answer was cached | Subsequent access to
restricted underlying content, citations, and cached answers is denied.

The cache is the interesting half. Denying the live query is the ordinary predicate doing its job;
what this scenario is really about is the answer that was already computed and stored while the
access was valid. Serving it afterwards would be a disclosure that no live query could produce.

The defence is the access epoch: ending a membership advances a counter in the same transaction,
and every answer keyed to the previous value stops being served — without anything having to go
and find it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import RoutePlan
from app.assistant import service as assistant_service
from app.assistant.models import AnswerCache
from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import service as evidence_service
from app.evidence.models import EvidenceSourceKind
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

AS_OF = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
QUESTION = "What was decided about the evaluation split on the retrieval project?"
# Shared with the project rather than owned by the student: a student's own report stays theirs
# after they leave, which is right. What must stop is reaching the project's shared material.
SHARED_TEXT = "Project decision: the evaluation split is frozen at the September snapshot."


async def _project_with_a_report(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
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
    # Joined before today, so the membership is live now and ending it today actually ends it:
    # `left_on` is exclusive (architecture §5.2).
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    await evidence_service.index_evidence(
        db,
        workspace_id=prof_scope.workspace_id,
        source_kind=EvidenceSourceKind.DECISION,
        source_id=project.id,
        source_version="1",
        text=SHARED_TEXT,
        visibility=Visibility.PROJECT_SHARED,
        locator=f"/projects/{project.id}#decisions",
        project_id=project.id,
        source_time=datetime(2026, 9, 16, tzinfo=UTC),
    )
    return period, project


async def _end_membership_today(db: AsyncSession, prof_scope: Scope, project: object) -> None:
    from app.core.clock import now

    memberships = await projects_service.list_members(db, prof_scope, project.id)
    await projects_service.end_membership(db, prof_scope, memberships[0].id, left_on=now().date())


def _gateway() -> FakeGateway:
    return FakeGateway(
        responses={"route_question": RoutePlan(intent="narrative", search_query="baseline")}
    )


async def test_ac_11_an_answer_cached_before_the_removal_is_not_served_after_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    _period, project = await _project_with_a_report(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    first = await assistant_service.ask(
        db, scope, question=QUESTION, as_of=AS_OF, gateway=_gateway()
    )
    assert first.cached is False

    served_again = await assistant_service.ask(
        db,
        await identity_service.scope_for(db, student_a),
        question=QUESTION,
        as_of=AS_OF,
        gateway=_gateway(),
    )
    assert served_again.cached is True, "the cache is doing something, or this proves nothing"

    await _end_membership_today(db, prof_scope, project)

    after = await assistant_service.ask(
        db,
        await identity_service.scope_for(db, student_a),
        question=QUESTION,
        as_of=AS_OF,
        gateway=_gateway(),
    )

    assert after.cached is False, "the cached answer died with the access it was written under"


async def test_ac_11_the_underlying_content_is_denied_to_the_removed_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    _period, project = await _project_with_a_report(db, prof_scope, student_a)
    before = await evidence_service.search_evidence(
        db,
        await identity_service.scope_for(db, student_a),
        query="evaluation split frozen",
        project_id=project.id,
    )
    assert before, "the member could read the project's shared material"

    await _end_membership_today(db, prof_scope, project)
    scope = await identity_service.scope_for(db, student_a)

    hits = await evidence_service.search_evidence(
        db, scope, query="evaluation split frozen", project_id=project.id
    )

    assert hits == []


async def test_ac_11_deactivating_a_user_invalidates_their_cached_answers_too(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """AUTH-03 names deactivation alongside membership removal, and the epoch covers both."""
    await _project_with_a_report(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    await assistant_service.ask(db, scope, question=QUESTION, as_of=AS_OF, gateway=_gateway())

    stored = (
        await db.execute(select(AnswerCache).where(AnswerCache.user_id == student_a.id))
    ).scalar_one()
    epoch_before = stored.access_epoch

    await identity_service.deactivate_user(db, prof_scope, student_a.id)
    epoch_after = await identity_service.access_epoch(db, prof_scope.workspace_id)

    assert epoch_after != epoch_before, (
        "deactivation must advance the epoch, or every answer cached for this user stays servable"
    )


async def test_ac_11_the_cache_is_keyed_by_the_asker_not_only_the_question(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    """QA-06: two people may ask the same words and be entitled to different answers."""
    await _project_with_a_report(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    await assistant_service.ask(db, scope, question=QUESTION, as_of=AS_OF, gateway=_gateway())
    professors_answer = await assistant_service.ask(
        db, prof_scope, question=QUESTION, as_of=AS_OF, gateway=_gateway()
    )

    assert professors_answer.cached is False, "the student's cached answer was not reused"
    rows = (
        await db.execute(
            select(func.count(AnswerCache.id)).where(
                AnswerCache.workspace_id == prof_scope.workspace_id
            )
        )
    ).scalar_one()
    assert rows == 2
