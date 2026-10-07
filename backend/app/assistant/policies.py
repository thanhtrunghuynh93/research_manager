"""Visibility predicates for assistant aggregates (AUTH-02, QA-06).

A conversation belongs to whoever had it. There is no sharing in the MVP, and the predicate says
so rather than leaving it to every caller to remember.
"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.sql import ColumnElement

from app.assistant.cache import read_set_digest
from app.assistant.models import AnswerCache, Conversation, Message
from app.core.authz import Scope, register_policy


@register_policy(Conversation)
def conversation_visible_to(scope: Scope) -> ColumnElement[bool]:
    """Own conversations only, professor included: these are private working notes, not records."""
    return and_(
        scope.within(Conversation.workspace_id),
        Conversation.owner_id == scope.user_id,
    )


@register_policy(Message)
def message_visible_to(scope: Scope) -> ColumnElement[bool]:
    return and_(
        scope.within(Message.workspace_id),
        Message.conversation_id.in_(select(Conversation.id).where(conversation_visible_to(scope))),
    )


@register_policy(AnswerCache)
def answer_cache_visible_to(scope: Scope) -> ColumnElement[bool]:
    """An answer cached for one person is never served to another, whatever their role (QA-06).

    A cached answer belongs to the workspace its asker was working in, and the same professor
    working elsewhere is a different entitlement; the fingerprint carries that workspace's epoch.
    """
    return and_(
        AnswerCache.workspace_id == scope.workspace_id,
        AnswerCache.user_id == scope.user_id,
        AnswerCache.epoch_fingerprint == read_set_digest(scope),
    )
