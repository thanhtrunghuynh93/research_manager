"""The assistant's use cases (QA-01..07, architecture §11).

One flow, in a fixed order, because the order is the safety property:

    route -> resolve entities against the database -> compute facts -> retrieve
    -> re-check permissions -> generate -> validate citations -> cache

Authorization is applied before retrieval and checked again before generation and before anything
is cached (QA-06). Numbers never pass through the model (QA-02). Nothing here changes a record: a
drafted message is text until a person sends it (QA-07).
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway, current_gateway
from app.assistant import answer as answer_module
from app.assistant import cache, facts, policies, retrieval, router  # noqa: F401  (policies)
from app.assistant import repository as repo
from app.assistant.models import Conversation, Message, MessageRole
from app.assistant.schemas import (
    AnswerOut,
    AnswerScope,
    CitationOut,
    ConversationOut,
    MessageOut,
)
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import NotFoundError
from app.core.ids import uuid7

log = logging.getLogger(__name__)

# Which questions are allowed to see the professor's own notes. Structural, not a prompt: the
# retrieval call simply is not made on a student's branch (QA-06, architecture §6.4).
PRIVATE_NOTE_INTENTS = frozenset({"narrative", "mixed"})


async def ask(
    session: AsyncSession,
    scope: Scope,
    *,
    question: str,
    conversation_id: UUID | None = None,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
    gateway: AIGateway | None = None,
    use_cache: bool = True,
) -> AnswerOut:
    """Answer one question within the caller's scope, and record the turn."""
    engine = gateway or current_gateway()
    asked_at = now()
    effective_as_of = as_of or asked_at

    conversation = await _conversation_for(
        session, scope, conversation_id=conversation_id, question=question
    )
    carried = _carry_scope(conversation, student_id=student_id, project_id=project_id)

    plan = await router.plan_question(
        session,
        scope,
        question=question,
        gateway=engine,
        as_of=effective_as_of,
        student_id=carried["student_id"],
        project_id=carried["project_id"],
        since=since,
        until=until,
    )

    answer_scope = AnswerScope(
        student_id=plan.student_id,
        student_name=plan.student_name,
        project_id=plan.project_id,
        project_name=plan.project_name,
        since=plan.since,
        until=plan.until,
        as_of=plan.as_of or effective_as_of,
        role=scope.role.value,
    )

    if plan.intent == "clarify" and plan.clarifying_question:
        # QA-05: a targeted question beats an answer about the wrong student.
        result = _clarification(question, answer_scope, plan, asked_at)
        result.conversation_id = conversation.id
        await _record_turn(session, scope, conversation, question, result)
        return result

    key = cache.key_for(scope, question, answer_scope.key())
    if use_cache:
        cached = await cache.get(
            session, scope, key, still_visible=_visibility_checker(session, scope)
        )
        if cached is not None:
            # The cached answer belongs to whichever conversation first asked; this turn is in
            # this one.
            cached.conversation_id = conversation.id
            await _record_turn(session, scope, conversation, question, cached)
            return cached

    computed = await _compute_facts(session, scope, plan, answer_scope)
    passages = await retrieval.retrieve(
        session,
        scope,
        query=plan.search_query or question,
        project_id=plan.project_id,
        since=plan.since,
        until=answer_scope.as_of,
        include_private=scope.is_prof and plan.intent in PRIVATE_NOTE_INTENTS,
    )

    result = await _assemble(
        session,
        scope,
        engine=engine,
        question=question,
        plan=plan,
        answer_scope=answer_scope,
        computed=computed,
        passages=passages,
        asked_at=asked_at,
    )

    if use_cache:
        await cache.put(session, scope, key, result)
    result.conversation_id = conversation.id
    await _record_turn(session, scope, conversation, question, result)
    return result


async def _compute_facts(
    session: AsyncSession, scope: Scope, plan: router.Plan, answer_scope: AnswerScope
) -> list[facts.Fact]:
    """Every number in the answer, computed in SQL under the caller's own scope (QA-02)."""
    query = facts.FactQuery(
        scope=scope,
        as_of=answer_scope.as_of,
        student_id=plan.student_id,
        project_id=plan.project_id,
        since=plan.since,
        until=plan.until,
    )
    computed: list[facts.Fact] = []
    for name in plan.fact_functions:
        try:
            fact = await facts.run(session, name, query)
        except Exception:  # noqa: BLE001 - one unanswerable fact must not lose the whole answer
            log.exception("fact function %s failed", name)
            continue
        if fact is not None:
            computed.append(fact)
    return computed


async def _assemble(
    session: AsyncSession,
    scope: Scope,
    *,
    engine: AIGateway,
    question: str,
    plan: router.Plan,
    answer_scope: AnswerScope,
    computed: list[facts.Fact],
    passages: list[retrieval.Passage],
    asked_at: datetime,
) -> AnswerOut:
    gaps = answer_module.coverage_gaps(computed, passages, plan.notes)
    prompt_versions = {"route_question": plan.prompt_version}

    if plan.intent == "fact":
        # AC-15: the number is the answer. No generation step can change it or soften it.
        return AnswerOut(
            id=uuid7(),
            question=question,
            scope=answer_scope,
            time_range=answer_module.time_range(answer_scope),
            answer=answer_module.render_facts_only(computed),
            facts=answer_module.facts_out(computed),
            citations=_citations_from_facts(computed),
            gaps=gaps,
            generated_at=asked_at,
            model_name=plan.model_name,
            prompt_versions=prompt_versions,
        )

    drafted = await answer_module.draft(
        session,
        scope,
        gateway=engine,
        question=question,
        answer_scope=answer_scope,
        computed=computed,
        passages=passages,
    )
    prompt_versions["answer"] = drafted.prompt_version

    if not drafted.ok or drafted.value is None:
        # QA-04: the facts stand on their own, and the failure is stated rather than hidden.
        reason = (
            "the AI budget for this month is spent, so no narrative was generated"
            if drafted.error == "delayed_budget"
            else "the narrative step did not complete, so only the computed facts are shown"
        )
        return AnswerOut(
            id=uuid7(),
            question=question,
            scope=answer_scope,
            time_range=answer_module.time_range(answer_scope),
            answer=answer_module.render_facts_only(computed),
            facts=answer_module.facts_out(computed),
            citations=_citations_from_facts(computed),
            gaps=[*gaps, reason],
            generated_at=asked_at,
            model_name=drafted.model,
            prompt_versions=prompt_versions,
        )

    citations, citation_gaps = answer_module.validate_citations(drafted.value, passages, computed)
    return AnswerOut(
        id=uuid7(),
        question=question,
        scope=answer_scope,
        time_range=answer_module.time_range(answer_scope),
        answer=drafted.value.answer,
        facts=answer_module.facts_out(computed),
        synthesis=[section.text for section in drafted.value.synthesis],
        suggestions=drafted.value.suggestions,
        citations=citations,
        gaps=[*gaps, *drafted.value.gaps, *citation_gaps],
        generated_at=asked_at,
        model_name=drafted.model,
        prompt_versions=prompt_versions,
    )


def _clarification(
    question: str, answer_scope: AnswerScope, plan: router.Plan, asked_at: datetime
) -> AnswerOut:
    return AnswerOut(
        id=uuid7(),
        question=question,
        scope=answer_scope,
        time_range=answer_module.time_range(answer_scope),
        answer=plan.clarifying_question,
        clarifying_question=plan.clarifying_question,
        gaps=plan.notes,
        generated_at=asked_at,
        model_name=plan.model_name,
        prompt_versions={"route_question": plan.prompt_version},
    )


def _citations_from_facts(computed: list[facts.Fact]) -> list[CitationOut]:
    seen: dict[str, CitationOut] = {}
    for fact in computed:
        for citation in fact.citations:
            seen.setdefault(
                str(citation.source_id),
                CitationOut(
                    source_kind=citation.source_kind,
                    source_id=citation.source_id,
                    source_version=citation.source_version,
                    locator=citation.locator,
                    label=citation.label,
                ),
            )
    return list(seen.values())


def _visibility_checker(session: AsyncSession, scope: Scope) -> object:
    """AC-11: a cached answer is served only if its sources are still the caller's to open.

    The epoch check in `cache.get` catches the structural changes; this catches an individual
    record that moved out of reach without the epoch moving.
    """

    async def _check(citations: list[CitationOut]) -> bool:
        from app.evidence import service as evidence_service

        for citation in citations:
            if citation.source_kind in ("report_entry", "evidence_reference"):
                chunks = await evidence_service.chunks_for_reference(session, citation.source_id)
                if chunks and not any(
                    _chunk_visible(chunk, scope) for chunk in chunks
                ):  # pragma: no cover - defence in depth behind the epoch check
                    return False
        return True

    return _check


def _chunk_visible(chunk: object, scope: Scope) -> bool:
    if scope.is_prof:
        return getattr(chunk, "workspace_id", None) == scope.workspace_id
    owner = getattr(chunk, "owner_student_id", None)
    project_id = getattr(chunk, "project_id", None)
    visibility = str(getattr(chunk, "visibility", ""))
    if visibility == "professor_only":
        return False
    if owner == scope.user_id:
        return True
    return project_id in scope.project_ids


# ------------------------------------------------------------------ conversations (QA-05)


async def _conversation_for(
    session: AsyncSession,
    scope: Scope,
    *,
    conversation_id: UUID | None,
    question: str,
) -> Conversation:
    if conversation_id is not None:
        existing = await repo.get_conversation(session, scope, conversation_id)
        if existing is None:
            raise NotFoundError("conversation not found")
        return existing

    conversation = Conversation(
        workspace_id=scope.workspace_id,
        owner_id=scope.user_id,
        title=question[:120],
        scope={},
    )
    session.add(conversation)
    await session.flush()
    return conversation


def _carry_scope(
    conversation: Conversation, *, student_id: UUID | None, project_id: UUID | None
) -> dict[str, UUID | None]:
    """QA-05: "compare that with last month" resolves against the conversation's active scope."""
    stored = conversation.scope or {}
    return {
        "student_id": student_id or _as_uuid(stored.get("student_id")),
        "project_id": project_id or _as_uuid(stored.get("project_id")),
    }


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value:
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


async def _record_turn(
    session: AsyncSession,
    scope: Scope,
    conversation: Conversation,
    question: str,
    result: AnswerOut,
) -> None:
    session.add(
        Message(
            workspace_id=scope.workspace_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            body=question,
        )
    )
    session.add(
        Message(
            workspace_id=scope.workspace_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            body=result.answer,
            answer=result.model_dump(mode="json"),
        )
    )
    conversation.scope = {
        "student_id": str(result.scope.student_id) if result.scope.student_id else None,
        "project_id": str(result.scope.project_id) if result.scope.project_id else None,
        "since": result.scope.since.isoformat() if result.scope.since else None,
        "until": result.scope.until.isoformat() if result.scope.until else None,
    }
    conversation.updated_at = now()
    await session.flush()


async def list_conversations(session: AsyncSession, scope: Scope) -> list[ConversationOut]:
    return [
        ConversationOut.model_validate(row) for row in await repo.list_conversations(session, scope)
    ]


async def list_messages(
    session: AsyncSession, scope: Scope, conversation_id: UUID
) -> list[MessageOut]:
    if await repo.get_conversation(session, scope, conversation_id) is None:
        raise NotFoundError("conversation not found")
    return [
        MessageOut.model_validate(row)
        for row in await repo.list_messages(session, scope, conversation_id)
    ]
