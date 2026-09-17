"""Visibility predicates for project aggregates, and the loader that fills a student's Scope.

AUTH-02: a project membership grants access to the project's shared records — never to another
student's private reports, assessments, or the professor's notes, which carry their own predicates.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy, register_project_ids_loader
from app.core.clock import now
from app.projects.models import (
    Milestone,
    PlanBaseline,
    Project,
    ProjectMembership,
    ResearchDecision,
    Task,
)


def _in_scope(
    model: type[Project] | type[Milestone] | type[Task] | type[ResearchDecision], scope: Scope
) -> ColumnElement[bool]:
    """The project a row belongs to must be one the caller may see."""
    project_column = Project.id if model is Project else model.project_id  # type: ignore[union-attr]
    same_workspace: ColumnElement[bool] = scope.within(model.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, project_column.in_(scope.project_ids))


@register_policy(Project)
def project_visible_to(scope: Scope) -> ColumnElement[bool]:
    return _in_scope(Project, scope)


@register_policy(Milestone)
def milestone_visible_to(scope: Scope) -> ColumnElement[bool]:
    return _in_scope(Milestone, scope)


@register_policy(Task)
def task_visible_to(scope: Scope) -> ColumnElement[bool]:
    return _in_scope(Task, scope)


@register_policy(ResearchDecision)
def research_decision_visible_to(scope: Scope) -> ColumnElement[bool]:
    return _in_scope(ResearchDecision, scope)


@register_policy(ProjectMembership)
def membership_visible_to(scope: Scope) -> ColumnElement[bool]:
    """UI-03: members of a project see who else works on it, including past members."""
    same_workspace = scope.within(ProjectMembership.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        or_(
            ProjectMembership.project_id.in_(scope.project_ids),
            ProjectMembership.student_id == scope.user_id,
        ),
    )


@register_policy(PlanBaseline)
def plan_baseline_visible_to(scope: Scope) -> ColumnElement[bool]:
    """A student sees the plan they are assessed against; the professor sees every plan."""
    same_workspace = scope.within(PlanBaseline.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        PlanBaseline.membership_id.in_(
            select(ProjectMembership.id).where(ProjectMembership.student_id == scope.user_id)
        ),
    )


@register_project_ids_loader
async def load_membership_project_ids(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> frozenset[UUID]:
    """The projects a student is currently a member of (architecture §6.1).

    `left_on` is exclusive — the first day the student is no longer a member — so ending a
    membership today revokes access today, which is what AUTH-03 asks for. A leave date set in the
    future keeps access until that day arrives.

    Project status does not gate access: a paused or archived project stays readable to the people
    who worked on it, which is what supervision history is for.
    """
    today = now().date()
    rows = await session.execute(
        select(ProjectMembership.project_id).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.student_id == user_id,
            ProjectMembership.joined_on <= today,
            or_(ProjectMembership.left_on.is_(None), ProjectMembership.left_on > today),
        )
    )
    return frozenset(rows.scalars().all())
