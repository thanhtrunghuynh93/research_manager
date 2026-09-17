"""Project use cases: the only entry point other modules may import.

Requirements PROJ-01..07. The professor owns the structural decisions — who is assigned, what is
active, what is open to joining — and since PROJ-07 a student may start a project of their own,
join one that has been opened, edit what they started, and leave. Everything else a student sees
here is read, granted by a membership (requirements §2).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.pagination import Page, clamp_limit
from app.core.types import Role
from app.identity import service as identity_service
from app.projects import policies, repository  # noqa: F401  (policies register on import)
from app.projects.models import (
    BaselineState,
    MembershipOrigin,
    Milestone,
    MilestoneRevision,
    MilestoneStatus,
    PlanBaseline,
    PlanBaselineItem,
    Project,
    ProjectMembership,
    ProjectStatus,
    ResearchDecision,
    ResearchStage,
    Task,
)
from app.projects.schemas import (
    JoinableProjectOut,
    MembershipOut,
    MilestoneOut,
    MilestoneRevisionOut,
    PlanBaselineItemOut,
    PlanBaselineOut,
    ProjectOut,
    ProjectProgressOut,
    ResearchDecisionOut,
    TaskOut,
    normalize_repo_url,
)

# A change to any of these alters what the milestone promised, so the previous state is retained
# as a revision (PROJ-06).
BASELINE_FIELDS = frozenset({"title", "success_criteria", "target_on", "weight", "status"})

# The columns a PATCH may set back to null. Everything else refuses one rather than handing a
# NOT NULL violation to the database.
PROJECT_CLEARABLE = frozenset({"target_on", "venue_target", "repo_url"})
MILESTONE_CLEARABLE = frozenset({"target_on", "owner_id", "change_reason"})
TASK_CLEARABLE = frozenset(
    {"blocker", "milestone_id", "assignee_id", "target_on", "completion_reason"}
)

# AUTH-07: what the person who started a project may change about it. Everything omitted here —
# `status`, `ai_restricted`, `open_to_join`, `shared_resources` — is a decision about the project's
# standing rather than its description, and stays with the professor.
CREATOR_FIELDS = frozenset(
    {
        "title",
        "description",
        "research_questions",
        "intended_contributions",
        "stage",
        "start_on",
        "target_on",
        "venue_target",
        "repo_url",
    }
)


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
    repo_url: str | None = None,
    shared_resources: dict[str, object] | None = None,
) -> ProjectOut:
    """PROJ-01. Either role may start a project; what differs is the status it starts in.

    A professor's starts `proposed`, because activation is where a second party's assent becomes
    visible and the professor is proposing work to someone else. A student starting their own has
    no second party to wait for, and a proposed project derives no obligation (REP-01) — so leaving
    it proposed would give them a project page, no weekly report, and nothing on screen to say why.
    The professor keeps the levers that matter afterwards: pause, archive, and whether anyone else
    may join.
    """
    project = Project(
        workspace_id=scope.workspace_id,
        title=title,
        description=description,
        stage=stage,
        status=ProjectStatus.PROPOSED if scope.is_prof else ProjectStatus.ACTIVE,
        research_questions=research_questions or [],
        intended_contributions=intended_contributions or [],
        start_on=start_on,
        target_on=target_on,
        venue_target=venue_target,
        repo_url=normalize_repo_url(repo_url),
        shared_resources=shared_resources or {},
        created_by=scope.user_id,
    )
    session.add(project)
    await session.flush()
    _audit(session, scope, "project.created", "projects", project.id, after={"title": title})
    if not scope.is_prof:
        # The creator is on the project they started. Not a convenience: without the membership the
        # project falls outside `scope.project_ids`, so nothing derives from it and the student
        # would be looking at a project that owes them nothing and tells them nothing.
        await _enrol(
            session, scope, project, student_id=scope.user_id, origin=MembershipOrigin.SELF_JOINED
        )
    return ProjectOut.model_validate(project)


async def join_project(
    session: AsyncSession, scope: Scope, project_id: UUID, *, responsibility: str = ""
) -> MembershipOut:
    """PROJ-07: a student puts themselves on a project the professor has opened.

    Resolved through `joinable_project` rather than `_require_project`, because the caller is not a
    member yet and the ordinary policy would answer 404. A project that is closed, archived, in
    another workspace, or one they are already on is simply not found — the same answer for all
    four, so this does not become a way to probe which projects exist.
    """
    if scope.is_prof:
        raise ForbiddenError("a professor does not hold a project membership")
    project = await repository.joinable_project(session, scope, project_id)
    if project is None:
        raise NotFoundError("project not found")
    membership = await _enrol(
        session,
        scope,
        project,
        student_id=scope.user_id,
        responsibility=responsibility,
        origin=MembershipOrigin.SELF_JOINED,
    )
    return MembershipOut.model_validate(membership)


async def list_joinable(
    session: AsyncSession, scope: Scope, *, limit: int = 50
) -> list[JoinableProjectOut]:
    if scope.is_prof:
        raise ForbiddenError("a professor does not join projects")
    return [
        JoinableProjectOut(
            id=project.id,
            title=project.title,
            stage=project.stage,
            status=project.status,
            member_count=count,
        )
        for project, count in await repository.joinable_projects(session, scope, limit=limit)
    ]


def _require_may_update_project(scope: Scope, project: Project, changes: dict[str, object]) -> None:
    """AUTH-07: the professor changes any project; the creator changes the record they wrote.

    The creator's set stops short of `status`, `ai_restricted` and `open_to_join`. Those are not
    description, they are governance: whether work is owed, whether the text may go to a model
    provider, and who else may read the project. `created_by` is nullable and carries no foreign
    key, so a row without one has no creator and falls to the professor alone.
    """
    if scope.is_prof:
        return
    if project.created_by is None or project.created_by != scope.user_id:
        raise ForbiddenError("only the professor or the project's creator may change it")
    # The keys, not the values: `ProjectPatch` is dumped with `exclude_unset=True`, so an explicit
    # null is a real edit and testing `is not None` would wave the clearable fields through.
    refused = sorted(set(changes) - CREATOR_FIELDS)
    if refused:
        raise ForbiddenError("only the professor may change: " + ", ".join(refused))


async def update_project(
    session: AsyncSession, scope: Scope, project_id: UUID, **changes: object
) -> ProjectOut:
    project = await _require_project(session, scope, project_id)
    _require_may_update_project(scope, project, changes)
    # Normalised here and not only in the schema: this is the entry point other modules and the
    # seed call, so a blank typed into the form and a blank passed by a job have to mean the same
    # absent rather than one of them leaving "   " in the column.
    if "repo_url" in changes:
        changes["repo_url"] = normalize_repo_url(changes["repo_url"])  # type: ignore[arg-type]
    applied = _apply(project, changes, clearable=PROJECT_CLEARABLE)
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


async def ai_restricted_for_job(
    session: AsyncSession, workspace_id: UUID, project_id: UUID
) -> bool:
    """Job-level read: may this project's text be sent to a model provider? (architecture §10)

    Unscoped like the other `_for_job` reads, because indexing runs in a worker with no Scope. It
    answers with the workspace pinned, and a project that is not there reads as restricted — the
    fail-closed direction for a question about sending research text off the host.
    """
    row = (
        await session.execute(
            select(Project.ai_restricted).where(
                Project.id == project_id, Project.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    return True if row is None else bool(row)


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
    """AUTH-01: only the professor puts *another* account on a project (PROJ-07 covers joining)."""
    scope.require_prof()
    project = await _require_project(session, scope, project_id)

    student = await identity_service.get_user(session, scope, student_id)
    if student.role is not Role.STUDENT:
        raise ConflictError("only a student can hold a project membership")

    return MembershipOut.model_validate(
        await _enrol(
            session,
            scope,
            project,
            student_id=student_id,
            responsibility=responsibility,
            joined_on=joined_on,
            planned_allocation=planned_allocation,
            origin=MembershipOrigin.ASSIGNED,
        )
    )


async def _enrol(
    session: AsyncSession,
    scope: Scope,
    project: Project,
    *,
    student_id: UUID,
    responsibility: str = "",
    joined_on: date | None = None,
    planned_allocation: Decimal | None = None,
    origin: MembershipOrigin,
) -> ProjectMembership:
    """Write one membership row, however it was asked for.

    Assignment and joining differ in who may ask and in what the row then owes; they must not
    differ in what gets written, or the two paths drift and only one of them is tested.
    """
    if await repository.active_membership(session, project.id, student_id) is not None:
        raise ConflictError("this student already has an active membership on the project")

    membership = ProjectMembership(
        workspace_id=scope.workspace_id,
        project_id=project.id,
        student_id=student_id,
        responsibility=responsibility,
        origin=origin,
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
        after={
            "project_id": str(project.id),
            "student_id": str(student_id),
            # The actor cannot tell these apart on its own — a student's scope writes both when
            # they create a project — and the audit table is the only durable record that a
            # student put themselves somewhere nobody sent them (PROJ-07).
            "origin": origin.value,
        },
    )
    # No epoch bump: granting access cannot invalidate an answer cached under narrower access.
    return membership


async def end_membership(
    session: AsyncSession, scope: Scope, membership_id: UUID, *, left_on: date | None = None
) -> MembershipOut:
    """PROJ-02 keeps the row; AUTH-03 revokes the access it granted.

    A student may end their own membership and no one else's (PROJ-07), and only as of today:
    a back-dated leave would rewrite which weeks were owed, and a forward-dated one would let them
    schedule an exit. The professor keeps both, which is what excusing a week properly looks like.
    """
    membership = await repository.get_membership(session, scope, membership_id)
    if membership is None:
        raise NotFoundError("membership not found")
    if not scope.is_prof:
        if membership.student_id != scope.user_id:
            raise ForbiddenError("only the professor or the student on it may end this membership")
        if left_on is not None and left_on != now().date():
            raise ValidationError("a student may only leave as of today")
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


async def _on_user_removed(event: Any, session: AsyncSession) -> None:
    """ADR 0011: a removed student leaves every project on the day they are removed.

    Obligations derive from memberships (REP-01), so this is what stops the weekly obligations and
    the reminders attached to them. Each row is closed directly rather than through
    `end_membership`: there is no Scope here, and the epoch has already been advanced by the
    removal itself, so bumping it once per project would be noise.
    """
    left_on = event.at.date()
    memberships = await repository.active_memberships_for_student(
        session, event.workspace_id, event.user_id
    )
    for membership in memberships:
        membership.left_on = left_on
        write_audit(
            session,
            workspace_id=event.workspace_id,
            actor_id=event.actor_id,
            action="membership.ended",
            target_table="project_memberships",
            target_id=membership.id,
            before={"left_on": None},
            after={"left_on": left_on.isoformat(), "reason": "user.removed"},
        )
    if memberships:
        await session.flush()


def register_subscriptions() -> None:
    """identity emits; projects reacts, which is how identity stays unaware of projects.

    Registration happens on import, like the visibility policies, so any process that can remove a
    user has already wired it. `subscribe` is idempotent.
    """
    from app.identity import events as identity_events

    identity_events.subscribe(identity_events.UserRemoved, _on_user_removed)


register_subscriptions()


async def list_members(
    session: AsyncSession, scope: Scope, project_id: UUID, *, include_past: bool = False
) -> list[MembershipOut]:
    await _require_project(session, scope, project_id)
    rows = await repository.list_memberships(session, scope, project_id, include_past=include_past)
    return [
        MembershipOut.model_validate(row).model_copy(update={"student_name": name})
        for row, name in rows
    ]


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
        field in BASELINE_FIELDS and getattr(milestone, field) != value
        for field, value in changes.items()
    )
    if baseline_changed and not change_reason:
        raise ValidationError("changing a milestone baseline requires a reason")

    applied = _apply(milestone, changes, clearable=MILESTONE_CLEARABLE)
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

    applied = _apply(task, changes, clearable=TASK_CLEARABLE)
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


# ------------------------------------------------------------------ plan baselines (PROJ-04)


async def freeze_baseline(
    session: AsyncSession,
    scope: Scope,
    *,
    membership_id: UUID,
    period_id: UUID,
    items: list[dict[str, Any]],
    source_entry_id: UUID | None = None,
) -> PlanBaselineOut:
    """Freeze the plan a week will be assessed against, at the start of that week.

    An empty plan is recorded as an `empty` baseline rather than skipped: the assessment needs to
    know that nothing was agreed, which is different from not having looked (PROJ-04, AC-18).
    """
    scope.require_prof()
    await _require_membership(session, scope, membership_id)
    existing = await repository.latest_baseline(
        session, scope, membership_id=membership_id, period_id=period_id
    )
    if existing is not None:
        raise ConflictError("this membership already has a baseline for the period")

    return await _insert_baseline(
        session,
        scope,
        membership_id=membership_id,
        period_id=period_id,
        version_no=1,
        state=BaselineState.FROZEN if items else BaselineState.EMPTY,
        items=items,
        source_entry_id=source_entry_id,
        frozen_at=now(),
        approved_by=scope.user_id if items else None,
    )


async def propose_baseline(
    session: AsyncSession,
    scope: Scope,
    *,
    membership_id: UUID,
    period_id: UUID,
    items: list[dict[str, Any]],
    source_entry_id: UUID | None = None,
) -> PlanBaselineOut:
    """AC-18: the student enters a first plan when the freeze point found nothing to freeze."""
    membership = await _require_membership(session, scope, membership_id)
    if not scope.is_prof and membership.student_id != scope.user_id:
        raise ForbiddenError("only the student on this membership may propose their plan")
    if not items:
        raise ValidationError("a proposed plan needs at least one outcome")

    latest = await repository.latest_baseline(
        session, scope, membership_id=membership_id, period_id=period_id
    )
    if latest is not None and latest.state in (BaselineState.FROZEN, BaselineState.ACCEPTED):
        raise ConflictError("a baseline is already in effect for this period")
    if latest is not None and latest.state is BaselineState.PROPOSED:
        return await supersede_baseline(
            session, scope, latest.id, items=items, reason="Replaced by a newer proposal"
        )

    await _supersede(session, latest)
    return await _insert_baseline(
        session,
        scope,
        membership_id=membership_id,
        period_id=period_id,
        version_no=1 if latest is None else latest.version_no + 1,
        state=BaselineState.PROPOSED,
        items=items,
        source_entry_id=source_entry_id,
        supersedes_id=None if latest is None else latest.id,
        proposed_by=scope.user_id,
    )


async def accept_baseline(
    session: AsyncSession, scope: Scope, baseline_id: UUID
) -> PlanBaselineOut:
    """ASSESS-05: a proposed plan becomes a commitment only when the professor accepts it."""
    scope.require_prof()
    baseline = await repository.get_baseline(session, scope, baseline_id)
    if baseline is None:
        raise NotFoundError("plan baseline not found")
    if baseline.state is not BaselineState.PROPOSED:
        raise ValidationError("only a proposed plan can be accepted")

    # Retired first, then accepted: `uq_baseline_in_effect` allows exactly one in-effect row per
    # membership and period, and acceptance is the moment the commitment changes hands. Until now
    # the superseded plan was the one in effect, which is what keeps a student from retiring the
    # plan they have not done and leaving the week measuring nothing (PROJ-04, ASSESS-05).
    if baseline.supersedes_id is not None:
        await _supersede(
            session, await repository.get_baseline(session, scope, baseline.supersedes_id)
        )

    baseline.state = BaselineState.ACCEPTED
    baseline.approved_by = scope.user_id
    baseline.approved_at = now()
    _audit(
        session,
        scope,
        "plan_baseline.accepted",
        "plan_baselines",
        baseline.id,
        after={"state": baseline.state.value},
    )
    await session.flush()
    return await _baseline_out(session, baseline)


async def supersede_baseline(
    session: AsyncSession,
    scope: Scope,
    baseline_id: UUID,
    *,
    items: list[dict[str, Any]],
    reason: str,
) -> PlanBaselineOut:
    """PROJ-04: a change is a new version with a reason; it never rewrites what was committed."""
    if not reason:
        raise ValidationError("changing an agreed plan requires a reason")
    previous = await repository.get_baseline(session, scope, baseline_id)
    if previous is None:
        raise NotFoundError("plan baseline not found")
    membership = await _require_membership(session, scope, previous.membership_id)
    if not scope.is_prof and membership.student_id != scope.user_id:
        raise ForbiddenError("only the student on this membership may propose a change")

    latest = await repository.latest_baseline(
        session, scope, membership_id=previous.membership_id, period_id=previous.period_id
    )
    if latest is not None and latest.state is BaselineState.PROPOSED:
        raise ConflictError("a proposed change to this plan is already waiting to be accepted")

    if scope.is_prof:
        # The replacement is frozen, so it takes effect the moment it exists.
        await _supersede(session, previous)
    # Otherwise the old plan stays in effect until the professor accepts the new one. Retiring it
    # first left *no* baseline in effect, so the assessment reported commitment completion as
    # unavailable rather than missed — a student could retire the plan they had not done on
    # Sunday night and the week would measure nothing (PROJ-04, ASSESS-05).

    # A professor-approved change is a commitment; a student's is a proposal until accepted.
    return await _insert_baseline(
        session,
        scope,
        membership_id=previous.membership_id,
        period_id=previous.period_id,
        version_no=previous.version_no + 1,
        state=BaselineState.FROZEN if scope.is_prof else BaselineState.PROPOSED,
        items=items,
        supersedes_id=previous.id,
        change_reason=reason,
        frozen_at=now() if scope.is_prof else None,
        approved_by=scope.user_id if scope.is_prof else None,
        proposed_by=None if scope.is_prof else scope.user_id,
    )


async def latest_baseline(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> PlanBaselineOut | None:
    """The newest version for this membership and period, in whatever state it is in."""
    baseline = await repository.latest_baseline(
        session, scope, membership_id=membership_id, period_id=period_id
    )
    return None if baseline is None else await _baseline_out(session, baseline)


async def effective_baseline(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> PlanBaselineOut | None:
    """The plan commitments are measured against, or None when completion is unavailable."""
    baseline = await repository.baseline_in_effect(
        session, scope, membership_id=membership_id, period_id=period_id
    )
    return None if baseline is None else await _baseline_out(session, baseline)


async def list_baselines(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> list[PlanBaselineOut]:
    rows = await repository.list_baselines(
        session, scope, membership_id=membership_id, period_id=period_id
    )
    return [await _baseline_out(session, row) for row in rows]


async def _insert_baseline(
    session: AsyncSession,
    scope: Scope,
    *,
    membership_id: UUID,
    period_id: UUID,
    version_no: int,
    state: BaselineState,
    items: list[dict[str, Any]],
    source_entry_id: UUID | None = None,
    supersedes_id: UUID | None = None,
    change_reason: str | None = None,
    frozen_at: datetime | None = None,
    proposed_by: UUID | None = None,
    approved_by: UUID | None = None,
) -> PlanBaselineOut:
    baseline = PlanBaseline(
        workspace_id=scope.workspace_id,
        membership_id=membership_id,
        period_id=period_id,
        version_no=version_no,
        state=state,
        frozen_at=frozen_at,
        source_entry_id=source_entry_id,
        supersedes_id=supersedes_id,
        change_reason=change_reason,
        proposed_by=proposed_by,
        approved_by=approved_by,
        approved_at=now() if approved_by else None,
    )
    session.add(baseline)
    await session.flush()

    for position, item in enumerate(items):
        session.add(
            PlanBaselineItem(
                workspace_id=scope.workspace_id,
                baseline_id=baseline.id,
                task_id=item.get("task_id"),
                planned_outcome=str(item["planned_outcome"]),
                weight=item.get("weight", 1),
                acceptance_criteria=str(item.get("acceptance_criteria", "")),
                position=position,
            )
        )
    _audit(
        session,
        scope,
        "plan_baseline.created",
        "plan_baselines",
        baseline.id,
        after={"state": state.value, "version_no": version_no},
    )
    await session.flush()
    return await _baseline_out(session, baseline)


async def _supersede(session: AsyncSession, baseline: PlanBaseline | None) -> None:
    """The only edit a baseline row allows: retiring it in favour of a later version."""
    if baseline is None or baseline.state is BaselineState.SUPERSEDED:
        return
    baseline.state = BaselineState.SUPERSEDED
    await session.flush()


async def _baseline_out(session: AsyncSession, baseline: PlanBaseline) -> PlanBaselineOut:
    items = await repository.baseline_items(session, baseline.id)
    out = PlanBaselineOut.model_validate(baseline)
    return out.model_copy(
        update={"items": [PlanBaselineItemOut.model_validate(item) for item in items]}
    )


async def _require_membership(
    session: AsyncSession, scope: Scope, membership_id: UUID
) -> ProjectMembership:
    membership = await repository.get_membership(session, scope, membership_id)
    if membership is None:
        raise NotFoundError("membership not found")
    return membership


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


async def effective_baseline_for_student(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
) -> PlanBaselineOut | None:
    """Job-level read: the plan commitments are measured against, or None (ASSESS-05)."""
    membership = await repository.active_membership(session, project_id, student_id)
    if membership is None:
        return None
    scope = Scope(
        workspace_id=workspace_id,
        user_id=student_id,
        role=Role.PROF,
        project_ids=frozenset({project_id}),
        access_epoch=0,
    )
    return await effective_baseline(
        session, scope, membership_id=membership.id, period_id=period_id
    )


async def project_title(session: AsyncSession, project_id: UUID) -> str:
    """Job-level read: the name to put in a notification, with no other project detail."""
    project = await session.get(Project, project_id)
    return "" if project is None else project.title


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


def _apply(
    row: object, changes: dict[str, object], *, clearable: frozenset[str] = frozenset()
) -> _Applied:
    """Assign the changes and report what actually moved, for the audit row.

    `None` used to mean "not supplied" for every field, which is not something a PATCH can say:
    the routers send `model_dump(exclude_unset=True)`, so an absent field is already absent and a
    null is a deliberate one. Conflating them meant a nullable field could never be cleared — a
    resolved `blocker` kept its old text and left `open_blockers` inflated for good.

    `clearable` names the columns a null may reach. A null for anything else is refused rather
    than passed to the database, so a mistyped request reads as a mistyped request.
    """
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    for field, value in changes.items():
        if not hasattr(row, field):
            continue
        if value is None and field not in clearable:
            raise ValidationError(f"{field} cannot be cleared")
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
        scope=scope,
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
