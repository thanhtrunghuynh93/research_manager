"""The research assistant (QA-01..07).

Read-only by construction: there is no endpoint here that changes a record. The assistant may draft
feedback or next steps, and sending, approving, or changing anything remains a separate action a
person takes elsewhere in the product (QA-07).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import ScopeDep, SessionDep
from app.assistant import service, stream
from app.assistant.schemas import AnswerOut, AskIn, ConversationOut, MessageOut

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", summary="Ask a question about the workspace's research")
async def ask(payload: AskIn, scope: ScopeDep, session: SessionDep) -> AnswerOut:
    """The answer carries its scope, its facts, its citations, and its gaps (QA-03)."""
    return await service.ask(
        session,
        scope,
        question=payload.question,
        conversation_id=payload.conversation_id,
        student_id=payload.student_id,
        project_id=payload.project_id,
        since=payload.since,
        until=payload.until,
        as_of=payload.as_of,
    )


@router.post("/ask/stream", summary="Ask, and watch the steps while it works")
async def ask_streaming(payload: AskIn, scope: ScopeDep, session: SessionDep) -> StreamingResponse:
    """Requirements §11: a first meaningful response inside ten seconds, and visible progress.

    Most of the wait is routing, facts and retrieval rather than generation, so the progress of
    those steps is what makes it legible. The answer contract is the same one `/ask` returns; it
    simply arrives in the order it becomes useful (architecture §11).
    """
    return StreamingResponse(
        stream.answer_stream(
            service.ask(
                session,
                scope,
                question=payload.question,
                conversation_id=payload.conversation_id,
                student_id=payload.student_id,
                project_id=payload.project_id,
                since=payload.since,
                until=payload.until,
                as_of=payload.as_of,
            )
        ),
        media_type="text/event-stream",
        headers=stream.SSE_HEADERS,
    )


@router.get("/conversations", summary="The caller's own conversations")
async def list_conversations(scope: ScopeDep, session: SessionDep) -> list[ConversationOut]:
    return await service.list_conversations(session, scope)


@router.get("/conversations/{conversation_id}/messages", summary="One conversation's turns")
async def list_messages(
    conversation_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[MessageOut]:
    return await service.list_messages(session, scope, conversation_id)
