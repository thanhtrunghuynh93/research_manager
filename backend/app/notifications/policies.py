"""Visibility predicates for notifications (AUTH-02, UI-07).

A notification is addressed to exactly one person. Even the professor reads only their own: the
contents are a message, not a record, and the professor's overview reads the underlying
obligations rather than other people's messages.
"""

from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.notifications.models import Notification, NotificationPreference


@register_policy(Notification)
def notification_visible_to(scope: Scope) -> ColumnElement[bool]:
    return and_(
        Notification.workspace_id == scope.workspace_id,
        Notification.recipient_id == scope.user_id,
    )


@register_policy(NotificationPreference)
def preference_visible_to(scope: Scope) -> ColumnElement[bool]:
    return and_(
        NotificationPreference.workspace_id == scope.workspace_id,
        NotificationPreference.user_id == scope.user_id,
    )
