"""Project use cases: the only entry point other modules may import.

Requirements PROJ-01..06. The professor owns every structural change; students read what their
membership grants them (requirements §2).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.pagination import Page, clamp_limit
from app.core.types import Role
from app.identity import service as identity_service
from app.projects import policies, repository  # noqa: F401  (policies register on import)
from app.projects.models import (
    Milestone,
    MilestoneRevision,
    MilestoneStatus,
    Project,
    ProjectMembership,
    ProjectStatus,
    ResearchDecision,
    ResearchStage,
    Task,
)
from app.projects.schemas import (
    MembershipOut,
    MilestoneOut,
    MilestoneRevisionOut,
    ProjectOut,
    ProjectProgressOut,
    ResearchDecisionOut,
    TaskOut,
)

# A change to any of these alters what the milestone promised, so the previous state is retained
# as a revision (PROJ-06).
BASELINE_FIELDS = frozenset({"title", "success_criteria", "target_on", "weight", "status"})


# ------------------------------------------------------------------ projects (PROJ-01)


async def create_project(
    session: AsyncSession,
    scope: Scope,
    *,
    title: str,
    description: str = "",
    stage: ResearchStage,
    research_questions: list[str] | None = None,
    intended_contributions: list[str] | None = None,
    start_on: date | None = None,
    target_on: date | None = None,
    venue_target: str | None = None,
    shared_resources: dict[str, object] | None = None,
) -> ProjectOut:
    scope.require_prof()
    project = Project(
        workspace_id=scope.workspace_id,
        title=title,
        description=description,
        stage=stage,
        status=ProjectStatus.PROPOSED,
        research_questions=research_questions or [],
        intended_contributions=intended_contributions or [],
        start_on=start_on,
        target_on=target_on,
        venue_target=venue_target,
        shared_resources=shared_resources or {},
        created_by=scope.user_id,
    )
    session.add(project)
    await session.flush()
    _audit(session, scope, "project.created", "projects", project.id, after={"title": title})
    return ProjectOut.model_validate(project)


async def update_project(
    session: AsyncSession, scope: Scope, project_id: UUID, **changes: object
) -> ProjectOut:
    scope.require_prof()
    project = await _require_project(session, scope, project_id)
    applied = _apply(project, changes)
    if applied:
        _audit(
            session,
            scope,
            "project.updated",
            "projects",
            project.id,
            before=applied.before,
            after=applied.after,
        )
        await session.flush()
    return ProjectOut.model_validate(project)


async def get_project(session: AsyncSession, scope: Scope, project_id: UUID) -> ProjectOut:
    return ProjectOut.model_validate(await _require_project(session, scope, project_id))


async def list_projects(
    session: AsyncSession,
    scope: Scope,
    *,
    status: ProjectStatus | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[ProjectOut]:
    size = clamp_limit(limit)
    rows, next_cursor = await repository.list_projects(
        session, scope, limit=size, cursor=cursor, status=status
    )
    return Page(
        items=[ProjectOut.model_validate(row) for row in rows],
        next_cursor=next_cursor,
        limit=size,
    )


async def project_progress(
    session: AsyncSession, scope: Scope, project_id: UUID
) -> ProjectProgressOut:
    """PROJ-06: milestone weights and accepted fractions; never an average of student scores."""
    await _require_project(session, scope, project_id)
    today = now().date()
    count, fraction, completed, overdue = await repository.milestone_progress(
        session, scope, project_id, today=today
    )
    return ProjectProgressOut(
        project_id=project_id,
        milestone_count=count,
        weighted_completion=None if fraction is None else round(Decimal(fraction), 4),
        completed_milestones=completed,
        overdue_milestones=overdue,
        open_blockers=await repository.count_open_blockers(session, scope, project_id),
    )


# ------------------------------------------------------------------ membership (PROJ-02)


async def add_member(
    session: AsyncSession,
    scope: Scope,
    project_id: UUID,
    *,
    student_id: UUID,
    responsibility: str = "",
    joined_on: date | None = None,
    planned_allocation: Decimal | None = None,
) -> MembershipOut:
    """AUTH-01: only the professor assigns students to projects."""
    scope.require_prof()
    project = await _require_project(session, scope, project_id)

    student = await identity_service.get_user(session, scope, student_id)
    if student.role is not Role.STUDENT:
        raise ConflictError("only a student can hold a project membership")

    if await repository.active_membership(session, project_id, student_id) is not None:
        raise ConflictError("this student already has an active membership on the project")

    membership = ProjectMembership(
        workspace_id=scope.workspace_id,
        project_id=project.id,
        student_id=student_id,
        responsibility=responsibility,
        joined_on=joined_on or now().date(),
        planned_allocation=planned_allocation,
    )
    session.add(membership)
    await session.flush()
    _audit(
        session,
        scope,
        "membership.added",
        "project_memberships",
        membership.id,
        after={"project_id": str(project_id), "student_id": str(student_id)},
    )
    # No epoch bump: granting access cannot invalidate an answer cached under narrower access.
    return MembershipOut.model_validate(membership)


async def end_membership(
    session: AsyncSession, scope: Scope, membership_id: UUID, *, left_on: date | None = None
) -> MembershipOut:
    """PROJ-02 keeps the row; AUTH-03 revokes the access it granted."""
    scope.require_prof()
    membership = await repository.get_membership(session, scope, membership_id)
    if membership is None:
        raise NotFoundError("membership not found")
    if membership.left_on is not None:
        return MembershipOut.model_validate(membership)

    membership.left_on = left_on or now().date()
    await identity_service.advance_access_epoch(session, scope.workspace_id)
    _audit(
        session,
        scope,
        "membership.ended",
        "project_memberships",
        membership.id,
        before={"left_on": None},
        after={"left_on": membership.left_on.isoformat()},
    )
    await session.flush()
    return MembershipOut.model_validate(membership)


async def list_members(
    session: AsyncSession, scope: Scope, project_id: UUID, *, include_past: bool = False
) -> list[MembershipOut]:
    await _require_project(session, scope, project_id)
    rows = await repository.list_memberships(session, scope, project_id, include_past=include_past)
    return [MembershipOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ milestones and tasks (PROJ-03)


async def create_milestone(
    session: AsyncSession, scope: Scope, project_id: UUID, **fields: object
) -> MilestoneOut:
    scope.require_prof()
    project = await _require_project(session, scope, project_id)
    milestone = Milestone(workspace_id=scope.workspace_id, project_id=project.id, **fields)
    session.add(milestone)
    await session.flush()
    _record_milestone_revision(session, scope, milestone, reason="created")
    _audit(
        session,
        scope,
        "milestone.created",
        "milestones",
        milestone.id,
        after={"title": milestone.title},
    )
    await session.flush()
    return MilestoneOut.model_validate(milestone)


async def update_milestone(
    session: AsyncSession,
    scope: Scope,
    milestone_id: UUID,
    *,
    change_reason: str | None = None,
    **changes: object,
) -> MilestoneOut:
    """PROJ-06: a change to scope, weight, or criteria retains the previous version."""
    scope.require_prof()
    milestone = await repository.get_milestone(session, scope, milestone_id)
    if milestone is None:
        raise NotFoundError("milestone not found")

    baseline_changed = any(
        field in BASELINE_FIELDS and value is not None and getattr(milestone, field) != value
        for field, value in changes.items()
    )
    if baseline_changed and not change_reason:
        raise ValidationError("changing a milestone baseline requires a reason")

    applied = _apply(milestone, changes)
    if not applied:
        return MilestoneOut.model_validate(milestone)

    if baseline_changed:
        milestone.revision_no += 1
        _record_milestone_revision(session, scope, milestone, reason=change_reason)
    _audit(
        session,
        scope,
        "milestone.updated",
        "milestones",
        milestone.id,
        before=applied.before,
        after=applied.after,
    )
    await session.flush()
    return MilestoneOut.model_validate(milestone)


async def list_milestones(
    session: AsyncSession, scope: Scope, project_id: UUID
) -> list[MilestoneOut]:
    await _require_project(session, scope, project_id)
    rows = await repository.list_milestones(session, scope, project_id)
    return [MilestoneOut.model_validate(row) for row in rows]


async def list_milestone_revisions(
    session: AsyncSession, scope: Scope, milestone_id: UUID
) -> list[MilestoneRevisionOut]:
    milestone = await repository.get_milestone(session, scope, milestone_id)
    if milestone is None:
        raise NotFoundError("milestone not found")
    rows = await repository.list_milestone_revisions(session, milestone_id)
    return [MilestoneRevisionOut.model_validate(row) for row in rows]


async def create_task(
    session: AsyncSession, scope: Scope, project_id: UUID, **fields: object
) -> TaskOut:
    scope.require_prof()
    project = await _require_project(session, scope, project_id)
    milestone_id = fields.get("milestone_id")
    if milestone_id is not None:
        await _require_milestone_in_project(session, scope, project.id, milestone_id)  # type: ignore[arg-type]

    task = Task(workspace_id=scope.workspace_id, project_id=project.id, **fields)
    session.add(task)
    await session.flush()
    _audit(session, scope, "task.created", "tasks", task.id, after={"title": task.title})
    return TaskOut.model_validate(task)


async def update_task(
    session: AsyncSession, scope: Scope, task_id: UUID, **changes: object
) -> TaskOut:
    """The professor edits the plan; a student may report progress on their own task."""
    task = await repository.get_task(session, scope, task_id)
    if task is None:
        raise NotFoundError("task not found")
    if not scope.is_prof:
        _require_student_may_update(scope, task, changes)

    fraction = changes.get("completion_fraction")
    if fraction is not None and not changes.get("completion_reason") and not task.completion_reason:
        # PROJ-03: partial completion must carry a reason.
        raise ValidationError("a completion fraction requires a reason")

    applied = _apply(task, changes)
    if applied:
        _audit(
            session,
            scope,
            "task.updated",
            "tasks",
            task.id,
            before=applied.before,
            after=applied.after,
        )
        await session.flush()
    return TaskOut.model_validate(task)


async def list_tasks(
    session: AsyncSession, scope: Scope, project_id: UUID, *, milestone_id: UUID | None = None
) -> list[TaskOut]:
    await _require_project(session, scope, project_id)
    rows = await repository.list_tasks(session, scope, project_id, milestone_id=milestone_id)
    return [TaskOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ research decisions


async def record_decision(
    session: AsyncSession,
    scope: Scope,
    project_id: UUID,
    *,
    decision: str,
    rationale: str = "",
    decided_on: date | None = None,
    participant_ids: list[UUID] | None = None,
    related_evidence: dict[str, object] | None = None,
) -> ResearchDecisionOut:
    scope.require_prof()
    project = await _require_project(session, scope, project_id)
    row = ResearchDecision(
        workspace_id=scope.workspace_id,
        project_id=project.id,
        decided_on=decided_on or now().date(),
        decision=decision,
        rationale=rationale,
        participant_ids=participant_ids or [],
        related_evidence=related_evidence or {},
        created_by=scope.user_id,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        scope,
        "decision.recorded",
        "research_decisions",
        row.id,
        after={"decision": decision},
    )
    return ResearchDecisionOut.model_validate(row)


async def list_decisions(
    session: AsyncSession, scope: Scope, project_id: UUID
) -> list[ResearchDecisionOut]:
    await _require_project(session, scope, project_id)
    rows = await repository.list_decisions(session, scope, project_id)
    return [ResearchDecisionOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ cross-module reads


async def reporting_memberships(
    session: AsyncSession, scope: Scope, *, local_start: date, local_end: date
) -> list[MembershipOut]:
    """The memberships that owe a report for the week between these dates (REP-01).

    Reporting calls this rather than reading membership rows itself, so the rules about active
    projects and exclusive leave dates live in one place.
    """
    rows = await repository.memberships_active_in_range(
        session, scope, local_start=local_start, local_end=local_end
    )
    return [MembershipOut.model_validate(row) for row in rows]


async def student_project_ids(
    session: AsyncSession, workspace_id: UUID, student_id: UUID
) -> frozenset[UUID]:
    """Used by identity to compile a Scope; also the answer to "which projects is X on?"."""
    return await policies.load_membership_project_ids(session, workspace_id, student_id)


# ------------------------------------------------------------------ helpers


class _Applied:
    def __init__(self, before: dict[str, object], after: dict[str, object]) -> None:
        self.before = before
        self.after = after

    def __bool__(self) -> bool:
        return bool(self.after)


def _apply(row: object, changes: dict[str, object]) -> _Applied:
    """Assign the non-None changes and report what actually moved, for the audit row."""
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    for field, value in changes.items():
        if value is None or not hasattr(row, field):
            continue
        current = getattr(row, field)
        if current == value:
            continue
        before[field] = _plain(current)
        after[field] = _plain(value)
        setattr(row, field, value)
    return _Applied(before, after)


def _plain(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value.value if hasattr(value, "value") else value


def _audit(
    session: AsyncSession,
    scope: Scope,
    action: str,
    table: str,
    target_id: UUID,
    *,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action=action,
        target_table=table,
        target_id=target_id,
        before=before,
        after=after,
    )


async def _require_project(session: AsyncSession, scope: Scope, project_id: UUID) -> Project:
    project = await repository.get_project(session, scope, project_id)
    if project is None:
        raise NotFoundError("project not found")
    return project


async def _require_milestone_in_project(
    session: AsyncSession, scope: Scope, project_id: UUID, milestone_id: UUID
) -> Milestone:
    milestone = await repository.get_milestone(session, scope, milestone_id)
    if milestone is None or milestone.project_id != project_id:
        raise ValidationError("the milestone belongs to a different project")
    return milestone


def _require_student_may_update(scope: Scope, task: Task, changes: dict[str, object]) -> None:
    student_fields = {"status", "completion_fraction", "completion_reason", "blocker"}
    if task.assignee_id != scope.user_id:
        raise NotFoundError("task not found")
    offered = {field for field, value in changes.items() if value is not None}
    if not offered <= student_fields:
        raise ValidationError("a student may only report progress on their own task")


def _record_milestone_revision(
    session: AsyncSession, scope: Scope, milestone: Milestone, *, reason: str | None
) -> None:
    session.add(
        MilestoneRevision(
            workspace_id=milestone.workspace_id,
            milestone_id=milestone.id,
            revision_no=milestone.revision_no,
            title=milestone.title,
            success_criteria=milestone.success_criteria,
            target_on=milestone.target_on,
            weight=milestone.weight,
            accepted_completion=milestone.accepted_completion,
            status=milestone.status or MilestoneStatus.PLANNED,
            change_reason=reason,
            changed_by=scope.user_id,
        )
    )
