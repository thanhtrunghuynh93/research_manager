"""Project use cases: the only entry point other modules may import.

Requirements PROJ-01..07. The professor owns the structural decisions — who is assigned, what is
active, what is open to joining — and since PROJ-07 a student may start a project of their own,
join one that has been opened, and edit what they started; ending a membership is the professor's
(ADR 0019). Everything else a student sees here is read, granted by a membership (requirements §2).
"""

from __future__ import annotations

from collections.abc import Collection
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
from app.projects import events, policies, repository  # noqa: F401  (policies register on import)
from app.projects.models import (
    BaselineState,
    MembershipOrigin,
    PlanBaseline,
    PlanBaselineItem,
    Project,
    ProjectMembership,
    ProjectStatus,
    ResearchStage,
)
from app.projects.schemas import (
    JoinableProjectOut,
    MembershipOut,
    PlanBaselineItemOut,
    PlanBaselineOut,
    ProjectOut,
    normalize_repo_url,
)

# The columns a PATCH may set back to null. Everything else refuses one rather than handing a
# NOT NULL violation to the database.
PROJECT_CLEARABLE = frozenset({"target_on", "venue_target", "repo_url"})

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
            session, scope, project, student_id=scope.user_id, origin=MembershipOrigin.CREATED
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
        for project, count in await repository.joinable_projects(
            session,
            scope,
            limit=limit,
            today=await identity_service.workspace_today(session, scope.workspace_id),
        )
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


async def _left_on_for(session: AsyncSession, scope: Scope) -> dict[UUID, date]:
    """Which of the caller's projects they have already left, and when. Empty for a professor."""
    if scope.is_prof:
        return {}
    today = await identity_service.workspace_today(session, scope.workspace_id)
    return await repository.ended_membership_dates(
        session, scope.workspace_id, scope.user_id, today=today
    )


async def get_project(session: AsyncSession, scope: Scope, project_id: UUID) -> ProjectOut:
    project = await _require_project(session, scope, project_id)
    left_on = (await _left_on_for(session, scope)).get(project.id)
    return ProjectOut.model_validate(project).model_copy(update={"viewer_left_on": left_on})


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
    # One lookup for the page, not one per row: a student's ended memberships are few and the
    # list is the only place that has to tell a project they are on from one they were on.
    left_on = await _left_on_for(session, scope)
    return Page(
        items=[
            ProjectOut.model_validate(row).model_copy(
                update={"viewer_left_on": left_on.get(row.id)}
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        limit=size,
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
    # The workspace's day, not UTC's: a membership dated in UTC is a date nothing else in the
    # system uses, and the access check and the reporting week both read it as workspace-local.
    joined_on = joined_on or await identity_service.workspace_today(session, scope.workspace_id)
    # Overlap, judged from the day the new row would start (`open_on`): a membership the
    # professor has dated to end later is still in force until then.
    if await repository.active_membership(session, project.id, student_id, on=joined_on):
        raise ConflictError("this student already has an active membership on the project")

    membership = ProjectMembership(
        workspace_id=scope.workspace_id,
        project_id=project.id,
        student_id=student_id,
        responsibility=responsibility,
        origin=origin,
        joined_on=joined_on,
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
    # Reporting subscribes and derives this week's obligation now rather than at 00:15 tomorrow,
    # which is what makes a project produce a report the moment it exists. projects cannot call
    # reporting — it sits above this module — so the event is how the two meet.
    await events.emit(
        events.MembershipStarted(
            workspace_id=membership.workspace_id,
            membership_id=membership.id,
            project_id=project.id,
            student_id=student_id,
            origin=origin.value,
        ),
        session,
    )
    return membership


async def end_membership(
    session: AsyncSession,
    scope: Scope,
    membership_id: UUID,
    *,
    left_on: date | None = None,
    project_id: UUID | None = None,
) -> MembershipOut:
    """PROJ-02 keeps the row; AUTH-03 revokes the access it granted.

    **Ending a membership is the professor's, including a student's own** (ADR 0019, amending
    PROJ-07 and ADR 0017). A student could end theirs and no one else's until this; the right came
    with starting and joining projects, and it is the half that was taken back. Leaving a project
    is not the same kind of act as joining one: the work was agreed with a supervisor, and whether
    it is finished is a supervision judgement rather than a student's to record.

    A professor ends a membership either directly — here — or by taking the project out of
    `ACTIVE`, which stops every membership on it owing a week (`memberships_open_through`). The
    second is usually what "this project is done" means, and it needs no row per student.

    `project_id` is the project the request named. A membership on any other project is not
    found under it, so a URL cannot end a membership it does not name.
    """
    if not scope.is_prof:
        raise ForbiddenError("only the professor may end a membership on a project")
    membership = await repository.get_membership(session, scope, membership_id)
    if membership is None or (project_id is not None and membership.project_id != project_id):
        raise NotFoundError("membership not found")
    # "Today" is the workspace's, the same day `joined_on` was written on and the same one the
    # access check reads it against.
    today = await identity_service.workspace_today(session, scope.workspace_id)
    if membership.left_on is not None:
        return MembershipOut.model_validate(membership)

    membership.left_on = left_on or today
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
    `end_membership`: there is no Scope here.
    """
    # The removal's day in the workspace, not in UTC: `left_on` is exclusive, so a removal just
    # after local midnight recorded against the UTC date would end the membership the day before
    # it happened and revoke a day of access retroactively.
    left_on = await identity_service.workspace_today(session, event.workspace_id)
    memberships = await repository.active_memberships_for_student(
        session, event.workspace_id, event.user_id, today=left_on
    )
    for membership in memberships:
        # One set to end later is pulled in to today, and its audit says what it was.
        before = membership.left_on.isoformat() if membership.left_on else None
        membership.left_on = left_on
        write_audit(
            session,
            workspace_id=event.workspace_id,
            actor_id=event.actor_id,
            action="membership.ended",
            target_table="project_memberships",
            target_id=membership.id,
            before={"left_on": before},
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
    today = await identity_service.workspace_today(session, scope.workspace_id)
    rows = await repository.list_memberships(
        session, scope, project_id, include_past=include_past, today=today
    )
    return [
        MembershipOut.model_validate(row).model_copy(update={"student_name": name})
        for row, name in rows
    ]


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
    frozen_at: datetime | None = None,
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


async def memberships_still_owing(
    session: AsyncSession, membership_ids: Collection[UUID], *, through: date
) -> set[UUID]:
    """Which of these memberships still owe a week ending on `through` (REP-01).

    Scope-free on purpose: the professor's outstanding list is computed for every student at once
    and has no caller scope to narrow by, and the answer is a property of the membership rather
    than of who is asking.

    Reporting calls this rather than reading membership rows itself, for the reason
    `memberships_active_in_range` gives: the rule about exclusive leave dates lives here, and an
    obligation already derived has to be judged by the same rule that would derive it today —
    otherwise a student stops being shown a project they left while the professor is still told
    they owe it.
    """
    return await repository.memberships_open_through(session, membership_ids, through=through)


async def effective_baseline_for_student(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
) -> PlanBaselineOut | None:
    """Job-level read: the plan commitments are measured against, or None (ASSESS-05)."""
    today = await identity_service.workspace_today(session, workspace_id)
    membership = await repository.active_membership(session, project_id, student_id, on=today)
    if membership is None:
        return None
    scope = Scope(
        workspace_id=workspace_id,
        user_id=student_id,
        role=Role.PROF,
        project_ids=frozenset({project_id}),
    )
    return await effective_baseline(
        session, scope, membership_id=membership.id, period_id=period_id
    )


async def project_title(session: AsyncSession, project_id: UUID) -> str:
    """Job-level read: the name to put in a notification, with no other project detail."""
    project = await session.get(Project, project_id)
    return "" if project is None else project.title


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
