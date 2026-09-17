"""Visibility predicate for notifications (AUTH-02, UI-07).

A notification is addressed to exactly one person. Even the professor reads only their own: the
contents are a message, not a record, and the professor's overview reads the underlying
obligations rather than other people's messages.

Use cases v0.3 retired the app's read path, so the only readers left are the delivery job and the
tests. The policy stays because the rows do: an unenforced predicate on a table nothing reads is
cheaper to keep than to reconstruct when a reader returns.
"""

from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.notifications.models import Notification


@register_policy(Notification)
def notification_visible_to(scope: Scope) -> ColumnElement[bool]:
    return and_(
        scope.within(Notification.workspace_id),
        Notification.recipient_id == scope.user_id,
    )
