"""The answer cache, and the two checks that stand between it and a disclosure (AC-11, QA-06).

An answer is expensive, and the same question asked twice in a meeting should not cost twice. But a
cached answer is a record of what someone was allowed to know *at the time it was written*, and
serving it later is a fresh disclosure decision.

So there are two gates, and they catch different things. The access epoch catches the structural
change — a membership ended, a user was deactivated, a visibility changed — because that advances a
counter and every answer keyed to the old one stops existing. Re-checking each citation catches the
rest: an individual record that has moved out of reach without the epoch moving.

Cheap and coarse first, then precise. Both, because either alone has a gap.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import AnswerCache
from app.assistant.schemas import AnswerOut
from app.core.authz import Scope
from app.core.clock import now

log = logging.getLogger(__name__)

# Long enough to serve a meeting, short enough that a stale answer does not outlive its week.
TTL = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class CacheKey:
    user_id: UUID
    question_hash: str
    scope_hash: str


def key_for(scope: Scope, question: str, scope_key: str) -> CacheKey:
    """Keyed by the asker as well as the question: same words, different entitlements (QA-06)."""
    return CacheKey(
        user_id=scope.user_id,
        question_hash=_digest(question.strip().lower()),
        scope_hash=_digest(scope_key),
    )


async def get(
    session: AsyncSession, scope: Scope, key: CacheKey, *, still_visible: object = None
) -> AnswerOut | None:
    """Return a cached answer only if it is still the caller's to see.

    `still_visible` is an async predicate over the citation list. It is passed in rather than
    imported so this module stays free of every source kind a citation might point at.
    """
    row = (
        await session.execute(
            select(AnswerCache).where(
                AnswerCache.user_id == key.user_id,
                AnswerCache.question_hash == key.question_hash,
                AnswerCache.scope_hash == key.scope_hash,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    if row.access_epoch != scope.access_epoch:
        # AUTH-03: something changed who may see what. The answer is gone, not re-checked.
        log.debug("cached answer discarded: access epoch moved")
        await session.delete(row)
        await session.flush()
        return None

    if (now() - row.created_at) > TTL:
        await session.delete(row)
        await session.flush()
        return None

    answer = AnswerOut.model_validate(row.answer)
    if still_visible is not None:
        allowed = await still_visible(answer.citations)  # type: ignore[operator]
        if not allowed:
            log.debug("cached answer discarded: a citation is no longer visible to the caller")
            await session.delete(row)
            await session.flush()
            return None

    return answer.model_copy(update={"cached": True})


async def put(session: AsyncSession, scope: Scope, key: CacheKey, answer: AnswerOut) -> None:
    await session.execute(
        insert(AnswerCache)
        .values(
            workspace_id=scope.workspace_id,
            user_id=key.user_id,
            question_hash=key.question_hash,
            scope_hash=key.scope_hash,
            access_epoch=scope.access_epoch,
            answer=answer.model_dump(mode="json"),
            created_at=now(),
        )
        .on_conflict_do_update(
            constraint="uq_answer_cache_key",
            set_={
                "access_epoch": scope.access_epoch,
                "answer": answer.model_dump(mode="json"),
                "created_at": now(),
            },
        )
    )
    await session.flush()


async def purge_stale(session: AsyncSession, workspace_id: UUID, current_epoch: int) -> int:
    """Housekeeping only. Correctness does not depend on this ever running (AC-11)."""
    result = await session.execute(
        delete(AnswerCache)
        .where(
            AnswerCache.workspace_id == workspace_id,
            AnswerCache.access_epoch != current_epoch,
        )
        .returning(AnswerCache.id)
    )
    return len(result.scalars().all())


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
