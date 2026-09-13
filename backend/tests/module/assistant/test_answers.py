"""The answer contract and what it refuses to do (QA-03, QA-04, QA-06, QA-07).

The assistant's value rests entirely on the professor being able to tell what it read from what it
inferred, and on being sure it cannot reach anything they could not. These tests are about those
two things rather than about answer quality, which is what the evaluation set is for.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import AnswerDraft, AnswerSection, RoutePlan
from app.assessment import service as assessment_service
from app.assistant import service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from tests.module.assistant.conftest import AFTER_THE_WEEK

pytestmark = pytest.mark.module


async def test_an_answer_states_its_time_range_and_its_scope(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """QA-03: an answer without its scope cannot be checked or followed up."""
    workspace = await build_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, workspace)

    answer = await service.ask(
        db,
        prof_scope,
        question="What did the team accomplish?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(),
    )

    assert answer.time_range
    assert answer.scope.as_of == AFTER_THE_WEEK
    assert answer.scope.role == "prof"
    assert answer.generated_at is not None


async def test_a_count_is_rendered_from_the_fact_and_never_from_the_model(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """AC-15/QA-02: the number in the answer is the number in the obligations table."""
    workspace = await build_week(db, prof_scope, [student_a, student_b])
    await submit_entry(db, student_a, workspace)
    gateway = FakeGateway(
        responses={
            "route_question": RoutePlan(intent="fact", fact_functions=["missing_reports"]),
            # If generation were consulted, this wrong number would surface.
            "answer": AnswerDraft(answer="Seventeen reports are missing."),
        }
    )

    answer = await service.ask(
        db,
        prof_scope,
        question="Which reports are missing this week?",
        as_of=AFTER_THE_WEEK,
        gateway=gateway,
    )

    assert "Seventeen" not in answer.answer
    assert "1" in answer.answer
    assert answer.facts[0].name == "missing_reports"
    assert answer.facts[0].value == 1
    assert "answer" not in gateway.calls, "a fact question never reaches the generation step"


async def test_a_citation_the_model_invented_is_dropped_and_the_drop_is_reported(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """AC-07: an answer quietly missing its support reads exactly like a well-supported one."""
    workspace = await build_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, workspace)
    gateway = FakeGateway(
        responses={
            "route_question": RoutePlan(intent="narrative", search_query="baseline"),
            "answer": AnswerDraft(
                answer="The baseline was reproduced.",
                synthesis=[
                    AnswerSection(
                        text="Confirmed by the run log.",
                        evidence_ref_ids=["99999999-9999-9999-9999-999999999999"],
                    )
                ],
                cited_evidence_ref_ids=["99999999-9999-9999-9999-999999999999"],
            ),
        }
    )

    answer = await service.ask(
        db,
        prof_scope,
        question="Was the baseline reproduced?",
        as_of=AFTER_THE_WEEK,
        gateway=gateway,
    )

    assert all(
        str(citation.source_id) != "99999999-9999-9999-9999-999999999999"
        for citation in answer.citations
    )
    assert any("did not match any retrieved record" in gap for gap in answer.gaps)


async def test_read_facts_and_inferred_synthesis_are_separate_fields(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """QA-03: the reader is entitled to know which is which."""
    workspace = await build_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, workspace)

    answer = await service.ask(
        db,
        prof_scope,
        question="How is the baseline work going?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(
            responses={"route_question": RoutePlan(intent="narrative", search_query="baseline")}
        ),
    )

    assert isinstance(answer.facts, list)
    assert isinstance(answer.synthesis, list)


# ------------------------------------------------------------------ confidentiality (QA-06)


async def test_a_supervision_note_never_reaches_a_students_answer(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """QA-06: the student branch does not make the call that would retrieve it."""
    workspace = await build_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, workspace)
    await assessment_service.add_supervision_note(
        db,
        prof_scope,
        body="Consider moving this student off the baseline work before the review.",
        student_id=student_a.id,
        project_id=workspace.project.id,
    )
    student_scope = await identity_service.scope_for(db, student_a)

    answer = await service.ask(
        db,
        student_scope,
        question="What does the professor think about the baseline work?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(),
    )

    assert "moving this student off" not in answer.answer
    assert all(citation.source_kind != "supervision_note" for citation in answer.citations)


async def test_a_student_cannot_read_another_students_work_through_the_assistant(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """AC-02: the same predicate that denies the API denies retrieval."""
    workspace = await build_week(db, prof_scope, [student_a, student_b])
    await submit_entry(
        db, student_a, workspace, work_performed="Discovered a leak in the evaluation split."
    )
    outsider = await identity_service.scope_for(db, student_b)

    answer = await service.ask(
        db,
        outsider,
        question="What did the other student discover about the evaluation split?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(),
    )

    assert "leak in the evaluation split" not in answer.answer
    assert all("leak" not in (citation.label or "") for citation in answer.citations)


async def test_a_student_asking_for_the_review_queue_gets_an_empty_one(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week
) -> None:
    await build_week(db, prof_scope, [student_a])
    student_scope = await identity_service.scope_for(db, student_a)

    answer = await service.ask(
        db,
        student_scope,
        question="What is waiting to review?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(responses={"route_question": RoutePlan(intent="fact")}),
    )

    queue = [fact for fact in answer.facts if fact.name == "review_queue"]
    assert queue == [] or queue[0].value == 0


# ------------------------------------------------------------------ uncertainty and failure


async def test_a_question_with_no_matching_records_says_so_rather_than_inventing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week
) -> None:
    """QA-04: say what is known and what cannot be established."""
    await build_week(db, prof_scope, [student_a])

    answer = await service.ask(
        db,
        prof_scope,
        question="What did the quantum annealing experiment show?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(
            responses={"route_question": RoutePlan(intent="narrative", search_query="annealing")}
        ),
    )

    assert answer.gaps, "an answer with nothing behind it must say so"


async def test_a_failed_generation_step_still_returns_the_computed_facts(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    build_week,
    submit_entry,
) -> None:
    """AC-13: the deterministic half of the answer does not depend on the provider."""
    workspace = await build_week(db, prof_scope, [student_a, student_b])
    await submit_entry(db, student_a, workspace)

    answer = await service.ask(
        db,
        prof_scope,
        question="Which reports are missing, and how is the work going?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(
            responses={
                "route_question": RoutePlan(
                    intent="mixed", fact_functions=["missing_reports"], search_query="baseline"
                )
            },
            fail_prompts={"answer"},
        ),
    )

    assert answer.facts[0].value == 1
    assert any("did not complete" in gap for gap in answer.gaps)


async def test_a_spent_budget_is_named_rather_than_looking_like_an_empty_answer(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week, submit_entry
) -> None:
    workspace = await build_week(db, prof_scope, [student_a])
    await submit_entry(db, student_a, workspace)
    await identity_service.set_ai_budgets(db, prof_scope, {"monthly_usd": "0"})

    from app.ai.gateway import OpenAIGateway

    class _NeverCalled:
        def __init__(self) -> None:
            self.chat = self
            self.completions = self

        async def parse(self, **kwargs: object) -> object:
            raise AssertionError("the budget check should have stopped this call")

    gateway = OpenAIGateway(
        client=_NeverCalled(), model="gpt-4.1", embed_model="text-embedding-3-small"
    )

    answer = await service.ask(
        db,
        prof_scope,
        question="How is the baseline work going?",
        as_of=AFTER_THE_WEEK,
        gateway=gateway,
    )

    assert any("budget" in gap for gap in answer.gaps)


# ------------------------------------------------------------------ conversations (QA-05)


async def test_a_turn_is_recorded_with_the_whole_answer_not_just_its_prose(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week
) -> None:
    await build_week(db, prof_scope, [student_a])

    await service.ask(
        db,
        prof_scope,
        question="When is the next deadline?",
        as_of=datetime(2026, 9, 15, tzinfo=UTC),
        gateway=FakeGateway(
            responses={"route_question": RoutePlan(intent="fact", fact_functions=["next_deadline"])}
        ),
    )

    conversations = await service.list_conversations(db, prof_scope)
    assert len(conversations) == 1
    messages = await service.list_messages(db, prof_scope, conversations[0].id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].answer["facts"]


async def test_a_conversation_belongs_to_whoever_had_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week
) -> None:
    await build_week(db, prof_scope, [student_a])
    await service.ask(
        db,
        prof_scope,
        question="When is the next deadline?",
        as_of=datetime(2026, 9, 15, tzinfo=UTC),
        gateway=FakeGateway(),
    )
    student_scope = await identity_service.scope_for(db, student_a)

    assert await service.list_conversations(db, student_scope) == []


async def test_an_ambiguous_name_produces_a_question_rather_than_a_guess(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, build_week
) -> None:
    """QA-05: answering about the wrong student is worse than asking which one."""
    from app.core.types import Role
    from tests.factories import make_user

    await build_week(db, prof_scope, [student_a])
    await make_user(db, await _workspace_of(db, prof_scope), role=Role.STUDENT, email="lan.a@x.edu")
    await make_user(db, await _workspace_of(db, prof_scope), role=Role.STUDENT, email="lan.b@x.edu")

    answer = await service.ask(
        db,
        prof_scope,
        question="How is Lan doing?",
        as_of=AFTER_THE_WEEK,
        gateway=FakeGateway(
            responses={"route_question": RoutePlan(intent="narrative", student_names=["lan"])}
        ),
    )

    assert answer.clarifying_question
    assert "lan" in answer.clarifying_question.lower()


async def _workspace_of(db: AsyncSession, scope: Scope) -> object:
    from app.identity.models import Workspace

    return await db.get(Workspace, scope.workspace_id)
