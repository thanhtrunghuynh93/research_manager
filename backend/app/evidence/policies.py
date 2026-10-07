"""Visibility predicate for evidence references (AUTH-02, QA-03)."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.core.types import Visibility
from app.evidence.models import EvidenceReference


@register_policy(EvidenceReference)
def evidence_reference_visible_to(scope: Scope) -> ColumnElement[bool]:
    """QA-03: opening a citation shows the same material the citation was allowed to be built from.

    The label on the reference is the one copied onto every chunk beneath it, so this says exactly
    what `index.retrieval.visible_chunks` says — stated once more here because `visible_to` fails
    closed, and without a policy the citation-open endpoint cannot run at all.
    """
    same_workspace: ColumnElement[bool] = scope.within(EvidenceReference.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        EvidenceReference.visibility != Visibility.PROFESSOR_ONLY,
        or_(
            and_(
                EvidenceReference.visibility == Visibility.PROJECT_SHARED,
                EvidenceReference.project_id.in_(scope.project_ids),
            ),
            and_(
                EvidenceReference.visibility == Visibility.STUDENT_PRIVATE,
                EvidenceReference.owner_student_id == scope.user_id,
            ),
        ),
    )
