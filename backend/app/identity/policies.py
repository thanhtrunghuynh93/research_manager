"""Visibility predicates for identity aggregates (AUTH-02, architecture §6.1).

Imported by identity.service, so any code path that reaches a user record has the policy registered.
"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.identity.models import User, WorkspaceMember


@register_policy(User)
def user_visible_to(scope: Scope) -> ColumnElement[bool]:
    """Professor: every account belonging to a workspace they belong to. Student: their own only.

    Membership rather than `users.workspace_id`, because those differ: the column says which
    workspace an account is *working in* and the membership says which it belongs to (ADR 0015). A
    colleague who belongs to a workspace I am in but is working in another of theirs is on my roll,
    and keying off the column would drop them off it.

    Students see co-members' names through the project membership list (PROJ-02); that read belongs
    to the projects module and carries its own predicate, `membership_visible_to`.
    """
    belongs_where_i_can_see = User.id.in_(
        select(WorkspaceMember.user_id).where(scope.within(WorkspaceMember.workspace_id))
    )
    if scope.is_prof:
        return belongs_where_i_can_see
    return and_(belongs_where_i_can_see, User.id == scope.user_id)
