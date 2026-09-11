"""Visibility predicates for identity aggregates (AUTH-02, architecture §6.1).

Imported by identity.service, so any code path that reaches a user record has the policy registered.
"""

from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.identity.models import User


@register_policy(User)
def user_visible_to(scope: Scope) -> ColumnElement[bool]:
    """Professor: every account in their workspace. Student: their own account only.

    Students see co-members' names through the project membership list once PROJ-02 lands; that
    read belongs to the projects module and carries its own predicate.
    """
    same_workspace = User.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, User.id == scope.user_id)
