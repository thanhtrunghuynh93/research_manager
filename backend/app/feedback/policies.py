"""Visibility predicates for feedback aggregates (ADR 0026).

A professor reads every feedback in the workspace they are in, drafts included (co-equal
professors, ADR 0011). A student reads a feedback only once it is published and only if it is about
them, and then only the published revision and its files — never a newer draft of the same record.
"""

from __future__ import annotations

from sqlalchemy import and_, select, tuple_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.feedback.models import (
    Feedback,
    FeedbackAttachment,
    FeedbackIdempotency,
    FeedbackRevision,
    FeedbackRevisionAttachment,
)


@register_policy(Feedback)
def feedback_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(Feedback.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        Feedback.student_id == scope.user_id,
        Feedback.published_version.is_not(None),
    )


@register_policy(FeedbackRevision)
def revision_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(FeedbackRevision.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        tuple_(FeedbackRevision.feedback_id, FeedbackRevision.version_no).in_(
            select(Feedback.id, Feedback.published_version).where(feedback_visible_to(scope))
        ),
    )


@register_policy(FeedbackRevisionAttachment)
def revision_attachment_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(FeedbackRevisionAttachment.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        FeedbackRevisionAttachment.revision_id.in_(
            select(FeedbackRevision.id).where(revision_visible_to(scope))
        ),
    )


@register_policy(FeedbackAttachment)
def attachment_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(FeedbackAttachment.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        FeedbackAttachment.id.in_(
            select(FeedbackRevisionAttachment.attachment_id).where(
                revision_attachment_visible_to(scope)
            )
        ),
    )


@register_policy(FeedbackIdempotency)
def idempotency_visible_to(scope: Scope) -> ColumnElement[bool]:
    """A key is its caller's: another professor's retry is not mine to replay."""
    return and_(
        scope.within(FeedbackIdempotency.workspace_id),
        FeedbackIdempotency.actor_id == scope.user_id,
    )
