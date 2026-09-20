"""Identity use cases: the only entry point other modules may import (docs/repo_layout.md §3.2).

Every mutation writes its audit row in the caller's transaction (architecture §5.3), and every
change to who may see what advances the workspace access epoch (AUTH-03).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope, load_project_ids
from app.core.clock import local_date, now
from app.core.config import get_settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)
from app.core.pagination import Page, clamp_limit
from app.core.types import ActorKind, Role
from app.identity import events, policies, repository, security  # noqa: F401  (policies register)
from app.identity.models import Invitation, PasswordReset, Session, User, UserState, Workspace
from app.identity.schemas import InvitationOut, UserOut, WorkspaceOut

log = logging.getLogger(__name__)

INVALID_CREDENTIALS = "invalid email or password"  # never says which of the two


@dataclass(frozen=True, slots=True)
class Invited:
    invitation: InvitationOut
    token: str


@dataclass(frozen=True, slots=True)
class LoggedIn:
    user: UserOut
    token: str


@dataclass(frozen=True, slots=True)
class AuthContext:
    scope: Scope
    user: UserOut
    session_id: UUID


@dataclass(frozen=True, slots=True)
class ResetRequested:
    user_id: UUID
    token: str


@dataclass(frozen=True, slots=True)
class RecoveryLink:
    user_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Bootstrapped:
    workspace: WorkspaceOut
    user: UserOut
    token: str


async def scope_for(session: AsyncSession, user: User) -> Scope:
    """Compile the per-request Scope (architecture §6.1).

    A professor sees every project in the workspace, so no membership lookup is needed; the
    predicates in each module's policies.py branch on the role.

    Two workspace fields, and the difference is the point (ADR 0016). `workspace_id` is where a
    write goes: the workspace this request is in, taken from the account. `workspace_ids` is what a
    read may see: every workspace the account belongs to.

    A student has one membership, so the two agree and nothing about their access changed. A
    professor belonging to several sees all of them and still writes into one.

    `project_ids` stays keyed to the single workspace. A student's project memberships live where
    their account does, and a professor does not use it — the predicates branch on the role.
    """
    project_ids = (
        frozenset()
        if user.role is Role.PROF
        else await load_project_ids(session, user.workspace_id, user.id)
    )
    workspace_ids = frozenset({user.workspace_id})
    if user.role is Role.PROF:
        joined = await repository.workspaces_joined_by(session, user.id)
        workspace_ids = frozenset({w.id for w in joined}) | workspace_ids

    # One query for every epoch the read-set spans, not one per workspace. `access_epoch` stays the
    # anchor's — a snapshot is built for one workspace — while `access_epochs` carries the rest, so
    # anything cached from a read that spanned can be validated against everything it spanned.
    epochs = await repository.access_epochs(session, workspace_ids)

    return Scope(
        workspace_id=user.workspace_id,
        user_id=user.id,
        role=user.role,
        project_ids=project_ids,
        access_epoch=epochs.get(user.workspace_id, 0),
        workspace_ids=workspace_ids,
        access_epochs=frozenset(epochs.items()),
    )


# ------------------------------------------------------------------ reads


async def get_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    user = await repository.get_visible_user(session, scope, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return UserOut.model_validate(user)


async def list_users(
    session: AsyncSession, scope: Scope, *, limit: int | None = None, cursor: str | None = None
) -> Page[UserOut]:
    """The roll, across every workspace the caller belongs to (ADR 0016).

    No flag: the User policy spans because `Scope.workspace_ids` does, so this is one read with one
    predicate rather than a widened variant of a narrow one. A student belongs to one workspace, so
    for them the answer is what it always was.
    """
    size = clamp_limit(limit)
    rows, next_cursor = await repository.list_visible_users(
        session, scope, limit=size, cursor=cursor
    )
    return Page(
        items=[UserOut.model_validate(row) for row in rows], next_cursor=next_cursor, limit=size
    )


async def advance_access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    """AUTH-03: call after any change elsewhere that narrows what someone may see.

    The projects module calls it when a membership ends; cached answers and snapshots built under
    the previous epoch stop being served (architecture §6.3).
    """
    return await repository.bump_access_epoch(session, workspace_id)


async def access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    """Job-level read: the epoch a snapshot or cached answer was built under (AUTH-03)."""
    return await repository.access_epoch(session, workspace_id)


async def ai_budgets(session: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
    """The workspace's monthly model-spending limits (requirements §11 "Cost control").

    A job-level read: the gateway checks a budget with no Scope to hand, and an empty result means
    no limit has been configured rather than a limit of zero.
    """
    return await repository.ai_budgets(session, workspace_id)


async def set_ai_budgets(
    session: AsyncSession, scope: Scope, budgets: dict[str, Any]
) -> dict[str, Any]:
    """The professor's decision about what may be spent, audited like any other setting."""
    scope.require_prof()
    before = await repository.ai_budgets(session, scope.workspace_id)
    after = await repository.set_ai_budgets(session, scope.workspace_id, budgets)
    write_audit(
        session,
        scope=scope,
        action="workspace.ai_budgets_set",
        target_table="workspaces",
        target_id=scope.workspace_id,
        before=before,
        after=after,
    )
    await session.flush()
    return after


async def workspace_ids(session: AsyncSession) -> list[UUID]:
    """Job-level read: the periodic tasks act on every workspace and have no Scope."""
    return await repository.workspace_ids(session)


async def system_scope(session: AsyncSession, workspace_id: UUID) -> Scope:
    """The Scope a scheduled task acts under: the workspace's professor, or nobody.

    Built rather than faked: the same predicates then apply to a job as to a request, and a task
    cannot reach further than the professor could.

    A workspace may hold several professors (ADR 0011). `professor_ids` is ordered, so the borrowed
    identity is stable across runs, and `is_system` marks it as a lens rather than an author — a
    write made under this Scope is audited as the system, not as whoever sorted first.
    """
    professors = await repository.professor_ids(session, workspace_id)
    return Scope(
        workspace_id=workspace_id,
        # No active professor is an ordinary state, not an error: it is what a workspace looks like
        # between bootstrap and the professor opening their invitation, and the calendar tasks must
        # still run through it. There is no user to borrow then, and `user_id` is not nullable —
        # eighty-odd call sites read it, several into non-null columns — so the workspace's own id
        # stands in as a value that resolves to no user.
        #
        # What makes that safe is that it can no longer be mistaken for an author: `is_system` sends
        # every audit row through `audit_actor`, which records SYSTEM and a null actor. Before
        # write_audit took a Scope this value reached the audit_events table directly, where it
        # named a user that does not exist.
        user_id=professors[0] if professors else workspace_id,
        role=Role.PROF,
        project_ids=frozenset(),
        access_epoch=await repository.access_epoch(session, workspace_id),
        is_system=True,
    )


async def professor_ids(session: AsyncSession, workspace_id: UUID) -> list[UUID]:
    """Job-level read: who to address a professor-facing notification to (UI-07)."""
    return await repository.professor_ids(session, workspace_id)


async def workspace_today(session: AsyncSession, workspace_id: UUID) -> date:
    """What day it is *in the workspace*, which is the only calendar its records are written on.

    `joined_on`, `left_on` and the reporting week are plain calendar dates in the workspace's own
    timezone, and `now().date()` is a date in UTC. The two disagree for seven hours of every day
    in a UTC+7 workspace, and the disagreement was not cosmetic: a student assigned to a project
    just after midnight local got a membership dated today-there and an access check run against
    yesterday-in-UTC, so the project owed them a report they could not attach a file to.

    A workspace that no longer exists has no local calendar to read, and UTC is then as good an
    answer as any — nothing can be written against it.
    """
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return now().date()
    return local_date(now(), workspace.timezone)


async def workspace_for_job(session: AsyncSession, workspace_id: UUID) -> WorkspaceOut | None:
    """Job-level read: the workspace an email names itself after. The worker has no Scope."""
    workspace = await session.get(Workspace, workspace_id)
    return None if workspace is None else WorkspaceOut.model_validate(workspace)


async def contact_for_job(session: AsyncSession, user_id: UUID) -> UserOut | None:
    """Job-level read: the address to send to. The worker has no Scope."""
    user = await repository.get_user_by_id(session, user_id)
    return None if user is None else UserOut.model_validate(user)


# ------------------------------------------------------------------ enrollment (AUTH-01)


# ------------------------------------------------------------------ workspaces (ADR 0012)


async def _require_owned_workspace(
    session: AsyncSession, scope: Scope, workspace_id: UUID
) -> Workspace:
    """The workspace this professor administers, or absent.

    Ownership is the administration relation (ADR 0012). A workspace the caller does not own is
    reported as absent rather than forbidden, for the reason every other read here gives: a 403
    would disclose that it exists (AC-02).
    """
    workspace = await repository.get_workspace(session, workspace_id)
    if workspace is None or workspace.owner_id != scope.user_id:
        raise NotFoundError("workspace not found")
    return workspace


async def _require_reachable_workspace(
    session: AsyncSession, scope: Scope, workspace_id: UUID
) -> Workspace:
    """A workspace this professor may enter or read: one they own, or one they belong to.

    The two relations answer different questions. Ownership decides what you may *acquire* and
    administer — create, rename, archive, invite into (ADR 0012). Membership decides what you may
    *be in*, and since ADR 0015 it is plural: joining one you already belong to moves only the
    anchor, which is how switching between them is spelled.

    Gating that on ownership made `Work here` unreachable for exactly the rows that offer it — a
    professor invited as a colleague belongs to a workspace they do not own, which is the case
    `list_workspaces` puts on the screen and this predicate has to agree with.

    Absent rather than forbidden, for the reason every other read here gives: a 403 would disclose
    that it exists (AC-02).
    """
    workspace = await repository.get_workspace(session, workspace_id)
    if workspace is None:
        raise NotFoundError("workspace not found")
    if workspace.owner_id == scope.user_id:
        return workspace
    if await repository.membership(session, workspace_id, scope.user_id) is not None:
        return workspace
    raise NotFoundError("workspace not found")


async def _require_invitable_workspace(
    session: AsyncSession, scope: Scope, workspace_id: UUID | None
) -> UUID:
    """Which workspace an invitation enrols into, having checked the caller may fill it."""
    if workspace_id is None or workspace_id == scope.workspace_id:
        own = await repository.get_workspace(session, scope.workspace_id)
        if own is not None and own.archived_at is not None:
            raise ValidationError("this workspace is archived")
        return scope.workspace_id

    workspace = await _require_owned_workspace(session, scope, workspace_id)
    if workspace.archived_at is not None:
        raise ValidationError("this workspace is archived")
    return workspace.id


async def _administered_workspace_ids(session: AsyncSession, scope: Scope) -> set[UUID]:
    """Every workspace this professor may act in: the ones they own or belong to, plus their own."""
    joined = await repository.workspaces_joined_by(session, scope.user_id)
    owned = await repository.workspaces_owned_by(session, scope.user_id)
    return {workspace.id for workspace in (*joined, *owned)} | {scope.workspace_id}


async def move_student(
    session: AsyncSession, scope: Scope, user_id: UUID, *, workspace_id: UUID
) -> UserOut:
    """Move one student to another workspace, if they have not written anything yet.

    A student's membership and their anchor have to agree — `Scope` is compiled from
    `users.workspace_id`, so a student belonging to one workspace and anchored in another would be
    scoped to a workspace they are not in. Both move together, which is why this is the one place
    the history foreign keys still bite.

    Four of the eight composite keys onto `users` do not cascade on update — `project_memberships`,
    `weekly_reports`, `developer_identities`, `contributions` — so Postgres refuses the move the
    moment a student has a project membership or a submitted report. That refusal is the rule
    "history stays in the workspace it was written in", and it is left to the database rather than
    reimplemented here: identity sits below projects, reporting and evidence in the layer order and
    cannot ask them what they hold (docs/repo_layout.md §3.2). The savepoint is what lets the
    refusal be caught and explained instead of aborting the request.

    So this moves a student who was enrolled into the wrong workspace, and refuses one who has
    started work. Moving the latter means deciding what happens to the work, which is a product
    decision nobody has made (use_cases.md §2.1).
    """
    scope.require_prof()
    administered = await _administered_workspace_ids(session, scope)

    target = await repository.get_workspace(session, workspace_id)
    if target is None or target.id not in administered:
        raise NotFoundError("workspace not found")
    if target.archived_at is not None:
        raise ValidationError("this workspace is archived")

    student = await repository.get_user_by_id(session, user_id)
    if student is None or student.workspace_id not in administered:
        raise NotFoundError("user not found")
    if student.role is Role.PROF:
        # ADR 0011: a professor moves themselves, by joining and leaving.
        raise ForbiddenError("a professor chooses their own workspaces; move only students here")
    if student.workspace_id == target.id:
        return UserOut.model_validate(student)

    source_id = student.workspace_id
    at = now()
    try:
        async with session.begin_nested():
            await repository.remove_membership(session, source_id, student.id)
            await repository.add_membership(session, target.id, student.id)
            student.workspace_id = target.id
            await session.flush()
    except IntegrityError as exc:
        # The account keeps rows that are pinned to the workspace they were written in.
        raise ValidationError(
            "this student has already done work in their workspace — project memberships, a "
            "submitted report, or attributed contributions — and that history cannot move with "
            "them. Only a student who has not started yet can be moved"
        ) from exc

    # Their visibility changed and they did not ask for it, so every session ends (AUTH-03). A
    # professor moving themselves keeps theirs; this is somebody else's account.
    await repository.revoke_sessions_for_user(session, student.id, at)
    await repository.bump_access_epoch(session, source_id)
    await repository.bump_access_epoch(session, target.id)
    write_audit(
        session,
        scope=scope,
        action="user.workspace_changed",
        target_table="users",
        target_id=student.id,
        before={"workspace_id": str(source_id)},
        after={"workspace_id": str(target.id)},
    )
    await session.flush()
    return UserOut.model_validate(student)


async def join_workspace(session: AsyncSession, scope: Scope, workspace_id: UUID) -> WorkspaceOut:
    """Add this professor to a workspace they may reach, and start working in it (ADR 0015).

    Belonging is plural: joining adds a `workspace_members` row and leaves every other membership
    alone, so a professor supervises in as many workspaces as they reach. What is singular is which
    one they are *working in* — `users.workspace_id`, the workspace a Scope is compiled from and
    the anchor every composite foreign key points at.

    So this is two things in one call, and they are different: you become a member, and that
    workspace becomes the one you see. Joining one you already belong to does only the second,
    which is how switching between them is spelled.

    The four identity foreign keys cascade, so an invitation, a session, a reset link and a
    notification follow the account as the anchor moves. The four history keys do not, so a student
    who has submitted anything cannot be moved at all — history stays where it was written.

    Reachable, not owned: a colleague belongs to a workspace they do not own and must still be able
    to work in it. ADR 0014 said "only one you own" when joining *was* moving; ADR 0015 made
    belonging plural and left switching behind the same call.
    """
    scope.require_prof()
    workspace = await _require_reachable_workspace(session, scope, workspace_id)
    if workspace.archived_at is not None:
        raise ValidationError("this workspace is archived")

    user = await repository.get_user_by_id(session, scope.user_id)
    if user is None:
        raise NotFoundError("user not found")

    await repository.add_membership(session, workspace.id, user.id)
    if user.workspace_id != workspace.id:
        await _move_anchor(session, scope, user, destination=workspace, action="workspace.joined")
    return WorkspaceOut.model_validate(workspace)


async def leave_workspace(session: AsyncSession, scope: Scope, workspace_id: UUID) -> WorkspaceOut:
    """Stop belonging to one workspace, keeping every other membership (ADR 0015).

    Leaving deletes the membership. It is refused when it would strand people: a workspace that
    still holds active accounts is never left without an active professor, which is AUTH-01's rule.
    Leaving the last account out is allowed, and is how a workspace becomes archivable.

    A professor who leaves the workspace they were *working in* has to land somewhere, because
    `users.workspace_id` is not nullable — so the anchor moves to another workspace they still
    belong to. Leaving your only membership is refused rather than guessed at: there would be
    nowhere for the account to live.
    """
    scope.require_prof()
    user = await repository.get_user_by_id(session, scope.user_id)
    if user is None:
        raise NotFoundError("user not found")
    if await repository.membership(session, workspace_id, user.id) is None:
        raise ValidationError("you do not belong to this workspace")

    remaining_profs = await repository.count_active_professors_in(
        session, workspace_id, excluding=user.id
    )
    if remaining_profs == 0:
        others = await repository.count_active_users(session, workspace_id) - 1
        if others > 0:
            raise ValidationError(
                f"{others} other active account(s) are in this workspace and you are its only "
                "professor; remove them, or add another professor, before leaving"
            )

    destination = await _another_joined_workspace(session, user.id, excluding=workspace_id)
    if destination is None:
        raise ValidationError(
            "this is the only workspace you belong to, and an account has to be in one; "
            "join or create another before leaving this"
        )

    await repository.remove_membership(session, workspace_id, user.id)
    if user.workspace_id == workspace_id:
        await _move_anchor(session, scope, user, destination=destination, action="workspace.left")
    else:
        await repository.bump_access_epoch(session, workspace_id)
        write_audit(
            session,
            scope=scope,
            action="workspace.left",
            target_table="users",
            target_id=user.id,
            before={"workspace_id": str(workspace_id)},
        )
        await session.flush()
    return WorkspaceOut.model_validate(destination)


async def _another_joined_workspace(
    session: AsyncSession, user_id: UUID, *, excluding: UUID
) -> Workspace | None:
    """Where the anchor lands when the workspace holding it is left. Oldest joined, or none."""
    joined = await repository.workspaces_joined_by(session, user_id)
    candidates = [w for w in joined if w.id != excluding]
    return candidates[0] if candidates else None


async def _move_anchor(
    session: AsyncSession, scope: Scope, user: User, *, destination: Workspace, action: str
) -> None:
    """Move which workspace this account is working in, without touching what it belongs to.

    The anchor is `users.workspace_id`: the workspace a Scope is compiled from and the parent of
    every composite foreign key. Membership is `workspace_members` and is not changed here.

    Sessions are deliberately *not* revoked. `sessions.workspace_id` cascades with the anchor, and
    `Scope` is compiled from the user row on every request, so the next request is already scoped
    to the new workspace. Ending the session instead would sign a professor out for the ordinary
    act of creating a workspace, to protect them from a move they just asked for.

    Both access epochs advance, which is the part AUTH-03 actually needs: cached answers and
    evidence snapshots were built under an access this account no longer has.
    """
    source_id = user.workspace_id
    user.workspace_id = destination.id
    await repository.bump_access_epoch(session, source_id)
    await repository.bump_access_epoch(session, destination.id)
    write_audit(
        session,
        scope=scope,
        action=action,
        target_table="users",
        target_id=user.id,
        before={"workspace_id": str(source_id)},
        after={"workspace_id": str(destination.id)},
    )
    await session.flush()


async def create_workspace(
    session: AsyncSession,
    scope: Scope,
    *,
    name: str,
    timezone: str = "Asia/Ho_Chi_Minh",
    join: bool = True,
) -> WorkspaceOut:
    """Create a workspace this professor owns, and join it (ADR 0014, 0015).

    Joining is the default because a workspace you just made and are not in is a confusing thing
    to be handed. It adds a membership and moves the anchor — where writes land and what a Scope is
    compiled from — and leaves every other membership alone, so the professor still belongs to, and
    reads, the workspace they came from. Emptying one is `leave_workspace`, which is what makes it
    archivable.

    `join=False` creates without moving, which is what a test setting up several workspaces wants.

    The new workspace starts with nobody else in it. Any further account arrives the only way any
    account arrives — an invitation naming it (AUTH-01). That is the difference from
    `app.cli identity bootstrap`, which creates a workspace *and* its first professor because it
    runs before any account exists. Here one already does.
    """
    scope.require_prof()
    workspace = Workspace(name=name.strip(), timezone=timezone, owner_id=scope.user_id)
    session.add(workspace)
    await session.flush()
    write_audit(
        session,
        scope=scope,
        action="workspace.created",
        target_table="workspaces",
        target_id=workspace.id,
        after={"name": workspace.name, "timezone": workspace.timezone},
    )
    await session.flush()

    if join:
        return await join_workspace(session, scope, workspace.id)
    return WorkspaceOut.model_validate(workspace)


async def list_workspaces(session: AsyncSession, scope: Scope) -> list[WorkspaceOut]:
    """Every workspace this professor belongs to, and every one they own.

    The two are different sets and the screen needs both. Belonging is what they can work in and
    leave; owning is what they may join and archive. A professor invited as a colleague belongs to
    a workspace they do not own, and one they created and later left is owned without being joined
    — so keying off either alone would hide a row they need.
    """
    scope.require_prof()
    joined = await repository.workspaces_joined_by(session, scope.user_id)
    owned = await repository.workspaces_owned_by(session, scope.user_id)
    member_of = {workspace.id for workspace in joined}
    return [
        WorkspaceOut.model_validate(workspace).model_copy(
            update={"joined": workspace.id in member_of}
        )
        for workspace in [*joined, *(w for w in owned if w.id not in member_of)]
    ]


async def get_workspace(session: AsyncSession, scope: Scope, workspace_id: UUID) -> WorkspaceOut:
    """Any row `list_workspaces` put on the screen: one they own, or one they belong to.

    The anchor needs no special case — it is a workspace the caller belongs to, so the reachable
    predicate already covers it.
    """
    scope.require_prof()
    return WorkspaceOut.model_validate(
        await _require_reachable_workspace(session, scope, workspace_id)
    )


async def update_workspace(
    session: AsyncSession,
    scope: Scope,
    workspace_id: UUID,
    *,
    name: str | None = None,
    timezone: str | None = None,
) -> WorkspaceOut:
    """Rename a workspace or change its default timezone. Owner only (ADR 0012).

    The timezone here is the default a new calendar starts from; it does not move an existing
    reporting calendar, which stays the versioned authority for period arithmetic (REP-01). A
    workspace already running a calendar therefore keeps its deadlines when this changes.
    """
    scope.require_prof()
    workspace = await _require_owned_workspace(session, scope, workspace_id)
    if workspace.archived_at is not None:
        raise ValidationError("this workspace is archived")

    before = {"name": workspace.name, "timezone": workspace.timezone}
    if name is not None:
        workspace.name = name.strip()
    if timezone is not None:
        workspace.timezone = timezone
    if before == {"name": workspace.name, "timezone": workspace.timezone}:
        return WorkspaceOut.model_validate(workspace)

    write_audit(
        session,
        scope=scope,
        action="workspace.updated",
        target_table="workspaces",
        target_id=workspace.id,
        before=before,
        after={"name": workspace.name, "timezone": workspace.timezone},
    )
    await session.flush()
    return WorkspaceOut.model_validate(workspace)


async def archive_workspace(
    session: AsyncSession, scope: Scope, workspace_id: UUID
) -> WorkspaceOut:
    """Close a workspace for good, once nobody is left in it.

    Archiving rather than deleting: every foreign key into a workspace cascades, so a delete would
    take its users, projects, reports and assessments with it and leave no audit row saying what
    happened. Refusing while any account is still active is what keeps the flag honest — an
    archived workspace has nobody who could be harmed by it not being enforced further down, so no
    other module has to learn about it.

    The workspace the caller works in is refused by name rather than by count. They are an active
    account in it and cannot deactivate or remove themselves (ADR 0011), so the counting message
    would be telling them to do something no route allows. Both refusals are written for the
    professor reading them rather than for whoever wrote the endpoint: the UI renders the API's
    own words (`components/Failure.tsx`), so a message about routes and break-glass procedures
    reaches a reader who has no idea what either is.
    """
    scope.require_prof()
    workspace = await _require_owned_workspace(session, scope, workspace_id)
    if workspace.archived_at is not None:
        return WorkspaceOut.model_validate(workspace)

    # The caller's *account*, not the workspace they are currently acting in: entering another
    # one does not move the account, so their own workspace still holds an active professor and
    # the counting message below would tell them to remove an account no route removes (ADR 0011).
    actor = await repository.get_user_by_id(session, scope.user_id)
    if actor is not None and workspace.id == actor.workspace_id:
        raise ValidationError(
            "your account lives in this workspace, so it cannot be archived. A workspace is "
            "archived only once nobody belongs to it, and moving an account out is done on the "
            "host rather than from here"
        )

    remaining = await repository.count_active_users(session, workspace.id)
    if remaining:
        raise ValidationError(
            f"{remaining} active account(s) remain; remove or deactivate them before archiving"
        )

    at = now()
    workspace.archived_at = at
    # An invited account is not an active one, so the count above lets a workspace with outstanding
    # invitations through. Those are offers to join something that no longer exists; withdrawing
    # them here is what stops an archived workspace acquiring its first member after the fact.
    withdrawn = await repository.revoke_workspace_invitations(session, workspace.id, at)
    write_audit(
        session,
        scope=scope,
        action="workspace.archived",
        target_table="workspaces",
        target_id=workspace.id,
        after={"archived_at": at.isoformat(), "invitations_withdrawn": withdrawn},
    )
    await session.flush()
    return WorkspaceOut.model_validate(workspace)


async def invite_user(
    session: AsyncSession,
    scope: Scope,
    *,
    email: str,
    display_name: str | None = None,
    role: Role = Role.STUDENT,
    workspace_id: UUID | None = None,
) -> Invited:
    """AUTH-01: only a professor enrolls people, and only by invitation.

    Any professor may invite a colleague as a professor; that is the only way a professor is added
    short of bootstrap or break-glass (ADR 0011). A role is fixed at acceptance: until then an
    invitation is an offer, and reissuing it at a different role is allowed — the role travels on
    the user row, which the re-invitation branch below updates. An account that has already
    accepted is refused here, so acceptance is the point after which only break-glass can move it.

    The invitation names the workspace it enrols into, which is why a student always has one from
    the moment they are invited. `workspace_id` defaults to the caller's own — what the caller's
    Scope always supplied implicitly — and may otherwise be any workspace this professor owns
    (ADR 0012). An archived workspace is refused: it has no active accounts by construction, and
    inviting into one would be the way to give it some.
    """
    scope.require_prof()
    target = await _require_invitable_workspace(session, scope, workspace_id)
    address = security.normalize_email(email)
    at = now()

    user = await repository.get_user_by_email(session, address)
    if user is not None and user.state is not UserState.INVITED:
        raise ConflictError("a user with this email already exists")
    if user is not None and user.workspace_id != target:
        # Across workspaces as well as within one: an address identifies one account, and moving
        # an existing one is `move_student`, not a second invitation.
        raise ConflictError("a user with this email already exists")

    if user is None:
        user = User(
            workspace_id=target,
            role=role,
            email=address,
            display_name=display_name or address.split("@")[0],
            state=UserState.INVITED,
        )
        session.add(user)
        await session.flush()
    else:
        # Re-invitation: the previous link stops working the moment a new one is issued.
        user.role = role
        if display_name:
            user.display_name = display_name
        await repository.revoke_pending_invitations(session, user.id, at)

    # The invitation is what makes them a member, not accepting it: the workspace's roll and the
    # count that guards archiving both read memberships, and an invited account is on the roll
    # from the moment it is invited (ADR 0015).
    await repository.add_membership(session, target, user.id)

    token, token_hash = security.mint_token()
    invitation = Invitation(
        workspace_id=target,
        user_id=user.id,
        email=address,
        role=role,
        token_hash=token_hash,
        expires_at=at + security.INVITATION_TTL,
        created_by=scope.user_id,
    )
    session.add(invitation)
    write_audit(
        session,
        scope=scope,
        action="user.invited",
        target_table="users",
        target_id=user.id,
        after={"email": address, "role": role.value, "workspace_id": str(target)},
    )
    await session.flush()

    await events.emit(
        events.InvitationCreated(
            workspace_id=target,
            user_id=user.id,
            email=address,
            display_name=user.display_name,
            token=token,
            expires_at=invitation.expires_at,
        ),
        session,
    )
    _log_token_link("invitation", address, f"/accept-invitation?token={token}")
    return Invited(invitation=InvitationOut.model_validate(invitation), token=token)


async def accept_invitation(
    session: AsyncSession, *, token: str, password: str, display_name: str | None = None
) -> UserOut:
    at = now()
    invitation = await repository.get_invitation_by_token(session, security.hash_token(token))
    if invitation is None or not _invitation_is_open(invitation, at):
        raise ValidationError("invitation token is invalid, used, or expired")

    user = await repository.get_user_in_workspace(
        session, invitation.workspace_id, invitation.user_id
    )
    if user is None:
        raise ValidationError("invitation token is invalid, used, or expired")
    if user.state is UserState.DEACTIVATED:
        # AUTH-03: deactivation has to be durable. An invitation issued before it — or still open
        # when it happened — must not be a way for the account holder to reinstate and sign in.
        # `deactivate_user` revokes open invitations, so reaching here means one was issued after.
        raise ValidationError("invitation token is invalid, used, or expired")

    # Hash before stamping the invitation: a rejected password must leave the link usable.
    password_hash = security.hash_password(password)
    user.password_hash = password_hash
    user.state = UserState.ACTIVE
    if user.role is not invitation.role:
        # AUTH-01: the most recent invitation wins. Re-inviting a not-yet-accepted account at a
        # different role updates the user row and leaves this older invitation's copy behind, so
        # taking the role off the invitation here would revert a decision already made and audited.
        log.info(
            "invitation for %s carried role %s; keeping the role %s set since",
            user.id,
            invitation.role.value,
            user.role.value,
        )
    if display_name:
        user.display_name = display_name
    invitation.accepted_at = at

    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="invitation.accepted",
        target_table="users",
        target_id=user.id,
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


def _invitation_is_open(invitation: Invitation, at: datetime) -> bool:
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > at
    )


# ------------------------------------------------------------------ sessions (AUTH-01, AUTH-03)


async def login(session: AsyncSession, *, email: str, password: str) -> LoggedIn:
    try:
        address = security.normalize_email(email)
    except ValidationError:
        security.verify_password(password, None)  # equalise timing for a malformed address
        raise UnauthenticatedError(INVALID_CREDENTIALS) from None

    user = await repository.get_user_by_email(session, address)
    stored = user.password_hash if user is not None and user.state is UserState.ACTIVE else None
    if not security.verify_password(password, stored) or user is None:
        raise UnauthenticatedError(INVALID_CREDENTIALS)

    if security.needs_rehash(user.password_hash or ""):
        user.password_hash = security.hash_password(password)

    return await _open_session(session, user)


async def start_session(session: AsyncSession, *, user_id: UUID) -> LoggedIn:
    """Open a session for someone who has just proved control of their mailbox.

    Used by invitation acceptance, where the token itself is the proof.
    """
    user = await repository.get_user_by_id(session, user_id)
    if user is None or user.state is not UserState.ACTIVE:
        raise UnauthenticatedError(INVALID_CREDENTIALS)
    return await _open_session(session, user)


async def _open_session(session: AsyncSession, user: User) -> LoggedIn:
    at = now()
    token, token_hash = security.mint_token()
    row = Session(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        created_at=at,
        last_seen_at=at,
        expires_at=security.absolute_expiry(at),
    )
    session.add(row)
    await session.flush()
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="session.created",
        target_table="sessions",
        target_id=row.id,
    )
    await session.flush()
    return LoggedIn(user=UserOut.model_validate(user), token=token)


async def resolve_session(session: AsyncSession, *, token: str) -> AuthContext | None:
    """Return the caller's Scope, or None when the token is unknown, revoked, or expired."""
    row = await repository.get_session_by_token(session, security.hash_token(token))
    if row is None:
        return None

    at = now()
    if row.expires_at <= at or security.is_idle_expired(row.last_seen_at, now=at):
        return None

    user = await repository.get_user_in_workspace(session, row.workspace_id, row.user_id)
    if user is None or user.state is not UserState.ACTIVE:
        return None

    if security.should_touch(row.last_seen_at, now=at):
        row.last_seen_at = at
        await session.flush()

    return AuthContext(
        scope=await scope_for(session, user),
        user=UserOut.model_validate(user),
        session_id=row.id,
    )


async def logout(session: AsyncSession, *, token: str) -> None:
    revoked = await repository.revoke_session_by_token(session, security.hash_token(token), now())
    _audit_session_revoked(session, revoked)
    await session.flush()


async def logout_session(session: AsyncSession, *, session_id: UUID) -> None:
    """Sign out the caller's own session.

    Identified by the resolved context rather than by the cookie value.
    """
    revoked = await repository.revoke_session_by_id(session, session_id, now())
    _audit_session_revoked(session, revoked)
    await session.flush()


def _audit_session_revoked(session: AsyncSession, revoked: Session | None) -> None:
    if revoked is None:
        return
    write_audit(
        session,
        workspace_id=revoked.workspace_id,
        actor_id=revoked.user_id,
        action="session.revoked",
        target_table="sessions",
        target_id=revoked.id,
    )


# ------------------------------------------------------------------ account lifecycle


async def deactivate_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    """AUTH-03: deactivation ends every session and advances the epoch in one transaction.

    Suspension, not removal: `reactivate_user` undoes it and project memberships are untouched.
    To take a student off the roll, use `remove_student`.
    """
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot deactivate their own account")

    user = await _require_user(session, scope, user_id)
    if user.role is Role.PROF:
        # ADR 0011: professors are equal over students and unequal over each other. Ejecting a
        # colleague is deliberate enough to require the host shell, where it is audited as system.
        raise ForbiddenError(
            "a professor account is deactivated through the break-glass procedure, not the API"
        )
    if user.state is UserState.DEACTIVATED:
        return UserOut.model_validate(user)

    at = now()
    before = user.state.value
    user.state = UserState.DEACTIVATED
    user.deactivated_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    # An open invitation is a credential too: accepting one sets a password and starts a session.
    await repository.revoke_pending_invitations(session, user.id, at)
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        scope=scope,
        action="user.deactivated",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    await events.emit(
        events.UserDeactivated(
            workspace_id=scope.workspace_id, user_id=user.id, actor_id=scope.user_id
        ),
        session,
    )
    return UserOut.model_validate(user)


async def reactivate_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    scope.require_prof()
    user = await _require_user(session, scope, user_id)
    if user.state is not UserState.DEACTIVATED:
        return UserOut.model_validate(user)

    before = user.state.value
    # Someone who never accepted their invitation returns to `invited`, not to a login they lack.
    user.state = UserState.ACTIVE if user.password_hash else UserState.INVITED
    user.deactivated_at = None
    # Removal deletes the membership (ADR 0015); suspension does not. Restoring has to put it back,
    # because every membership-keyed read — the roll, the account's own record, the count that
    # decides whether a workspace may be archived — would otherwise not see an account that can
    # sign in again. `add_membership` is idempotent, so restoring a merely suspended account is
    # unchanged. The anchor names the workspace because that is where this account's history is
    # pinned; here it equals `scope.workspace_id`, which `_require_user` resolved through.
    await repository.add_membership(session, user.workspace_id, user.id)
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        scope=scope,
        action="user.reactivated",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def remove_student(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    """AUTH-01/PROJ-02: take a student off the roll — memberships end, then the account closes.

    Deactivating alone is not removal. Obligations are derived from memberships and nothing in that
    path filters on user state, so a student who only lost their login keeps accruing weekly
    obligations and the reminders that go with them. Ending the memberships in the same transaction
    is what stops that (ADR 0011).

    The ledger survives: submitted reports, assessments, artifacts and attributed commits stay, and
    the membership rows remain as history carrying `left_on`. Removal is not reversible — a student
    who returns is invited again and comes back with fresh memberships.

    `UserRemoved` carries the membership-ending to the projects module, which subscribes to it.
    identity sits below projects in the layer order and so cannot call it directly.
    """
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot remove their own account")

    user = await _require_user(session, scope, user_id)
    if user.role is Role.PROF:
        # ADR 0011: the API removes students. A professor leaving is a break-glass transfer.
        raise ForbiddenError(
            "a professor account is removed through the break-glass procedure, not the API"
        )

    at = now()
    before = user.state.value
    already_closed = user.state is UserState.DEACTIVATED
    user.state = UserState.DEACTIVATED
    user.deactivated_at = user.deactivated_at if already_closed else at
    await repository.revoke_sessions_for_user(session, user.id, at)
    # An open invitation is a credential too: accepting one sets a password and starts a session.
    await repository.revoke_pending_invitations(session, user.id, at)
    # Off the roll means off the membership: the count that guards archiving reads it, and a
    # removed student must not keep a workspace occupied (ADR 0015). The account row stays where
    # it is — `users.workspace_id` anchors their history and cannot move once they have any.
    await repository.remove_membership(session, scope.workspace_id, user.id)
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        scope=scope,
        action="user.removed",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    await events.emit(
        events.UserRemoved(
            workspace_id=scope.workspace_id, user_id=user.id, actor_id=scope.user_id, at=at
        ),
        session,
    )
    return UserOut.model_validate(user)


async def update_profile(
    session: AsyncSession,
    scope: Scope,
    *,
    display_name: str | None = None,
) -> UserOut:
    user = await _require_user(session, scope, scope.user_id)
    before = {"display_name": user.display_name}
    if display_name:
        user.display_name = display_name
    write_audit(
        session,
        scope=scope,
        action="user.profile_updated",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"display_name": user.display_name},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def _require_user(session: AsyncSession, scope: Scope, user_id: UUID) -> User:
    user = await repository.get_user_in_workspace(session, scope.workspace_id, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return user


# ------------------------------------------------------------------ recovery (AUTH-01)


async def request_password_reset(session: AsyncSession, *, email: str) -> ResetRequested | None:
    """Return None for an address that cannot receive a reset, without saying why."""
    try:
        address = security.normalize_email(email)
    except ValidationError:
        return None

    user = await repository.get_user_by_email(session, address)
    if user is None or user.state is not UserState.ACTIVE:
        return None

    at = now()
    await repository.revoke_pending_password_resets(session, user.id, at)
    token, token_hash = security.mint_token()
    reset = PasswordReset(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=at + security.PASSWORD_RESET_TTL,
    )
    session.add(reset)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="password_reset.requested",
        target_table="users",
        target_id=user.id,
    )
    await session.flush()

    await events.emit(
        events.PasswordResetRequested(
            workspace_id=user.workspace_id,
            user_id=user.id,
            email=address,
            display_name=user.display_name,
            token=token,
            expires_at=reset.expires_at,
        ),
        session,
    )
    _log_token_link("password reset", address, f"/reset-password?token={token}")
    return ResetRequested(user_id=user.id, token=token)


async def reset_password(session: AsyncSession, *, token: str, password: str) -> UserOut:
    at = now()
    reset = await repository.get_password_reset_by_token(session, security.hash_token(token))
    if (
        reset is None
        or reset.used_at is not None
        or reset.revoked_at is not None
        or reset.expires_at <= at
    ):
        raise ValidationError("reset token is invalid, used, or expired")

    user = await repository.get_user_in_workspace(session, reset.workspace_id, reset.user_id)
    if user is None or user.state is not UserState.ACTIVE:
        raise ValidationError("reset token is invalid, used, or expired")

    # Hash before consuming the token: a rejected password must leave the link usable.
    user.password_hash = security.hash_password(password)
    reset.used_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="password_reset.completed",
        target_table="users",
        target_id=user.id,
    )
    await session.flush()
    return UserOut.model_validate(user)


# ------------------------------------------------------------------ bootstrap and break-glass


async def bootstrap_workspace(
    session: AsyncSession,
    *,
    name: str,
    prof_email: str,
    prof_display_name: str,
    timezone: str = "Asia/Ho_Chi_Minh",
) -> Bootstrapped:
    """Create the workspace and its professor. Run once, from the host (app.cli)."""
    address = security.normalize_email(prof_email)
    if await repository.get_user_by_email(session, address) is not None:
        raise ConflictError("a user with this email already exists")

    at = now()
    workspace = Workspace(name=name, timezone=timezone)
    session.add(workspace)
    await session.flush()

    user = User(
        workspace_id=workspace.id,
        role=Role.PROF,
        email=address,
        display_name=prof_display_name,
        state=UserState.INVITED,
    )
    session.add(user)
    await session.flush()
    await repository.add_membership(session, workspace.id, user.id)
    # The owner administers this workspace — creates, renames, archives it, and accepts students
    # moved into it (ADR 0012). It is also the break-glass contact, which `transfer_professor`
    # moves. Co-equality between professors is unchanged within a workspace (ADR 0011).
    workspace.owner_id = user.id

    token, token_hash = security.mint_token()
    session.add(
        Invitation(
            workspace_id=workspace.id,
            user_id=user.id,
            email=address,
            role=Role.PROF,
            token_hash=token_hash,
            expires_at=at + security.INVITATION_TTL,
        )
    )
    write_audit(
        session,
        workspace_id=workspace.id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="workspace.bootstrapped",
        target_table="workspaces",
        target_id=workspace.id,
        after={"owner_email": address},
    )
    await session.flush()
    return Bootstrapped(
        workspace=WorkspaceOut.model_validate(workspace),
        user=UserOut.model_validate(user),
        token=token,
    )


async def _require_another_active_professor(
    session: AsyncSession, workspace_id: UUID, *, excluding: UUID
) -> None:
    """ADR 0011: a workspace never runs out of professors.

    With one professor this was guaranteed by the self-action guards — nobody could act on the only
    account that mattered. With a set of co-equal professors that reasoning no longer holds, so the
    invariant is checked rather than inferred.
    """
    if await repository.count_active_professors(session, workspace_id, excluding=excluding) == 0:
        raise ConflictError(
            "this is the only active professor in the workspace; transfer the account instead"
        )


async def demote_professor(session: AsyncSession, *, email: str) -> UserOut:
    """AUTH-01 break-glass: return a professor to the student role, from the host shell only.

    Not reachable from the API: professors are equal over students and unequal over each other, so
    one cannot unilaterally demote another (ADR 0011).
    """
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")
    if user.role is not Role.PROF:
        raise ValidationError(f"{address} is not a professor")
    await _require_another_active_professor(session, user.workspace_id, excluding=user.id)

    before = {"role": user.role.value}
    user.role = Role.STUDENT
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass_demote",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"role": Role.STUDENT.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def deactivate_professor(session: AsyncSession, *, email: str) -> UserOut:
    """AUTH-01 break-glass: close a professor account, from the host shell only (ADR 0011)."""
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")
    if user.role is not Role.PROF:
        raise ValidationError(f"{address} is not a professor")
    if user.state is UserState.DEACTIVATED:
        return UserOut.model_validate(user)
    await _require_another_active_professor(session, user.workspace_id, excluding=user.id)

    at = now()
    before = {"state": user.state.value}
    user.state = UserState.DEACTIVATED
    user.deactivated_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    await repository.revoke_pending_invitations(session, user.id, at)
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass_deactivate",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def revoke_all_sessions(session: AsyncSession) -> int:
    """End every session in the deployment at once (docs/runbooks/rotate-secrets.md).

    For a suspected leak, where the holder of a stolen cookie is unknown and revoking account by
    account would leave a window. Sessions are opaque rows rather than signed payloads
    (app/identity/security.py), so this — not a configuration change — is what ends them: there is
    no key whose rotation invalidates a session, and nothing else in the system does this.

    Deliberately narrower than its name might suggest: pending invitation and password-reset
    tokens keep their own TTLs and are untouched. Revoking those is per-account today
    (`repository.revoke_pending_invitations`), and the runbook says so rather than implying a
    reach this does not have.
    """
    at = now()
    counts = await repository.revoke_all_sessions(session, at)
    for workspace_id, revoked in counts.items():
        write_audit(
            session,
            workspace_id=workspace_id,
            actor_id=None,
            actor_kind=ActorKind.SYSTEM,
            action="identity.revoke_all_sessions",
            target_table="sessions",
            target_id=None,
            after={"revoked": revoked},
        )
    await session.flush()
    return sum(counts.values())


async def recover_professor(session: AsyncSession, *, email: str) -> RecoveryLink:
    """AUTH-01 break-glass: restore professor access from the host shell only.

    Runs from `app.cli breakglass recover-professor`, never from the API. It issues a short-lived
    single-use recovery link rather than a password, so the secret is handed over out of band, and
    it writes a system-actor audit row (docs/runbooks/break-glass.md, architecture §6.2).
    """
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")

    before = {"role": user.role.value, "state": user.state.value}
    # The lock-out may be the demotion or deactivation itself, so recovery undoes both.
    user.role = Role.PROF
    user.state = UserState.ACTIVE
    user.deactivated_at = None
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"role": Role.PROF.value, "state": UserState.ACTIVE.value},
    )
    return await _issue_recovery_link(session, user, ttl=security.BREAK_GLASS_RESET_TTL)


async def transfer_professor(
    session: AsyncSession, *, from_email: str, to_email: str, display_name: str | None = None
) -> RecoveryLink:
    """AUTH-01 break-glass: hand the workspace to another person in one transaction."""
    previous_address = security.normalize_email(from_email)
    successor_address = security.normalize_email(to_email)
    if previous_address == successor_address:
        raise ValidationError("the successor must be a different account")

    previous = await repository.get_user_by_email(session, previous_address)
    if previous is None:
        raise NotFoundError(f"no account with the address {previous_address}")

    workspace_id = previous.workspace_id
    successor = await repository.get_user_by_email(session, successor_address)
    if successor is not None and successor.workspace_id != workspace_id:
        raise ConflictError("that email belongs to another workspace")
    if successor is None:
        successor = User(
            workspace_id=workspace_id,
            role=Role.PROF,
            email=successor_address,
            display_name=display_name or successor_address.split("@")[0],
            state=UserState.ACTIVE,
        )
        session.add(successor)
        await session.flush()

    at = now()
    successor_before = {"role": successor.role.value, "state": successor.state.value}
    previous_before = {"state": previous.state.value}
    successor.role = Role.PROF
    successor.state = UserState.ACTIVE
    successor.deactivated_at = None
    if display_name:
        successor.display_name = display_name

    previous.state = UserState.DEACTIVATED
    previous.deactivated_at = at
    await repository.revoke_sessions_for_user(session, previous.id, at)
    # The owner is the workspace's break-glass contact (ADR 0011). A transfer moves it; leaving it
    # on a deactivated account would point the next recovery at someone who has already left.
    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None and workspace.owner_id == previous.id:
        workspace.owner_id = successor.id
    await repository.bump_access_epoch(session, workspace_id)

    for target, before, after in (
        (
            successor,
            successor_before,
            {"role": Role.PROF.value, "state": UserState.ACTIVE.value},
        ),
        (previous, previous_before, {"state": UserState.DEACTIVATED.value}),
    ):
        write_audit(
            session,
            workspace_id=workspace_id,
            actor_id=None,
            actor_kind=ActorKind.SYSTEM,
            action="identity.break_glass_transfer",
            target_table="users",
            target_id=target.id,
            before=before,
            after=after,
        )
    return await _issue_recovery_link(session, successor, ttl=security.BREAK_GLASS_RESET_TTL)


async def _issue_recovery_link(
    session: AsyncSession, user: User, *, ttl: timedelta
) -> RecoveryLink:
    at = now()
    await repository.revoke_pending_password_resets(session, user.id, at)
    token, token_hash = security.mint_token()
    reset = PasswordReset(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=at + ttl,
    )
    session.add(reset)
    await session.flush()

    # The notifications module tells the address on record that recovery happened (step 4).
    await events.emit(
        events.PasswordResetRequested(
            workspace_id=user.workspace_id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            token=token,
            expires_at=reset.expires_at,
        ),
        session,
    )
    return RecoveryLink(user_id=user.id, token=token, expires_at=reset.expires_at)


def _log_token_link(kind: str, address: str, path: str) -> None:
    """Development convenience beside the email, which notifications now sends (AUTH-01).

    Kept because a dev stack without SMTP still needs a way in, and because a link in the log is
    faster to reach than one in Mailpit. Outside dev only the fact of the delivery is logged; the
    token never reaches the log.
    """
    settings = get_settings()
    if settings.env == "dev":
        log.info("%s link for %s: %s%s", kind, address, settings.public_url, path)
    else:
        log.info("%s issued for %s", kind, address)
