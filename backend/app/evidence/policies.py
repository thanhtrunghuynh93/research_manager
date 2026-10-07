"""Visibility predicate for evidence chunks (AUTH-02)."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.core.types import Visibility
from app.evidence.models import EvidenceChunk


@register_policy(EvidenceChunk)
def evidence_chunk_visible_to(scope: Scope) -> ColumnElement[bool]:
    """The one place a chunk becomes eligible to be read on someone's behalf.

    The label is copied from the reference onto every chunk beneath it, so this filters without a
    join. The professor sees every chunk in their workspace. A student sees material shared with a
    project they are currently on, and their own private material — never another student's, and
    never anything labelled professor-only.
    """
    same_workspace: ColumnElement[bool] = scope.within(EvidenceChunk.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        EvidenceChunk.visibility != Visibility.PROFESSOR_ONLY,
        or_(
            and_(
                EvidenceChunk.visibility == Visibility.PROJECT_SHARED,
                EvidenceChunk.project_id.in_(scope.project_ids),
            ),
            and_(
                EvidenceChunk.visibility == Visibility.STUDENT_PRIVATE,
                EvidenceChunk.owner_student_id == scope.user_id,
            ),
        ),
    )
