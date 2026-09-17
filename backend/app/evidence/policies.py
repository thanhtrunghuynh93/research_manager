"""Visibility predicates for evidence aggregates (AUTH-02, REPO-04).

A student sees the repository events their own contributions point at — which is what lets them
challenge a misattribution (REPO-04) — and never another student's attributed work.
"""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.core.types import Visibility
from app.evidence.models import (
    Contribution,
    DeveloperIdentity,
    EvidenceReference,
    ProjectRepository,
    Repository,
    RepositoryEvent,
    SyncRun,
)


@register_policy(Repository)
def repository_visible_to(scope: Scope) -> ColumnElement[bool]:
    """A student sees a repository connected to a project they are on (UI-03)."""
    same_workspace = scope.within(Repository.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        Repository.id.in_(
            select(ProjectRepository.repository_id).where(
                ProjectRepository.project_id.in_(scope.project_ids)
            )
        ),
    )


@register_policy(ProjectRepository)
def project_link_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(ProjectRepository.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, ProjectRepository.project_id.in_(scope.project_ids))


@register_policy(SyncRun)
def sync_run_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(SyncRun.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        SyncRun.repository_id.in_(select(Repository.id).where(repository_visible_to(scope))),
    )


@register_policy(RepositoryEvent)
def event_visible_to(scope: Scope) -> ColumnElement[bool]:
    """The professor sees every event; a student sees the ones attributed to them (REPO-04)."""
    same_workspace = scope.within(RepositoryEvent.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        RepositoryEvent.id.in_(
            select(Contribution.event_id).where(Contribution.student_id == scope.user_id)
        ),
    )


@register_policy(Contribution)
def contribution_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(Contribution.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, Contribution.student_id == scope.user_id)


@register_policy(DeveloperIdentity)
def identity_visible_to(scope: Scope) -> ColumnElement[bool]:
    """REPO-04: each student can see the identity mappings attributed to them."""
    same_workspace = scope.within(DeveloperIdentity.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, DeveloperIdentity.student_id == scope.user_id)


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
