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
    """Who may read a project *record*: a member, its creator (AUTH-07), and anyone who was on it.

    The extra terms are on `Project` alone and not in `_in_scope`, which `Milestone`, `Task` and
    `ResearchDecision` share: widening it there would hand a non-member every milestone and every
    decision in the workspace in the same edit. Here each grants exactly the row a person is
    entitled to — the creator's, because they may change fields they must be able to read; and a
    past member's, because their own history refers to it.

    That last term is the one to read against AUTH-03, which says ending a membership "must
    invalidate subsequent access" and, in the same breath, "preserve historical records for
    authorized supervision". The access AUTH-03 is protecting is the project's *ongoing work* —
    its milestones, its tasks including another student's blockers, its decisions, its evidence and
    the identity of everyone on it — and `scope.project_ids` still gates every one of those, which
    is what §8.4 means by a membership being the entire grant. What it does not need to protect is
    the title of a project a student spent a term on: without it their own retained records — a
    submitted report, an approved assessment, this week's obligation, all keyed to `student_id` and
    all still theirs to read — render as a bare uuid, and the project page they arrive at from one
    is a refusal. Leaving a project should end the work, not unname it.
    """
    if scope.is_prof:
        return scope.within(Project.workspace_id)
    was_ever_on = select(ProjectMembership.project_id).where(
        ProjectMembership.workspace_id == Project.workspace_id,
        ProjectMembership.student_id == scope.user_id,
    )
    return and_(
        scope.within(Project.workspace_id),
        or_(
            Project.id.in_(scope.project_ids),
            Project.created_by == scope.user_id,
            Project.id.in_(was_ever_on),
        ),
    )


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
