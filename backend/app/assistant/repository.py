"""Queries over the assistant tables. No business rules here (docs/repo_layout.md §3.2)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import Conversation, Message
from app.core.authz import Scope, visible_to


async def get_conversation(
    session: AsyncSession, scope: Scope, conversation_id: UUID
) -> Conversation | None:
    return (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, visible_to(scope, Conversation)
            )
        )
    ).scalar_one_or_none()


async def list_conversations(
    session: AsyncSession, scope: Scope, *, limit: int = 50
) -> list[Conversation]:
    return list(
        (
            await session.execute(
                select(Conversation)
                .where(visible_to(scope, Conversation))
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def list_messages(
    session: AsyncSession, scope: Scope, conversation_id: UUID
) -> list[Message]:
    return list(
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id, visible_to(scope, Message))
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
