"""Workspaces: ownership (ADR 0012), moving (ADR 0014) and plural membership (ADR 0015).

What these pin down is the boundary, not the CRUD. A workspace is the tenant boundary, so the
interesting cases are the ones that would cross it: renaming a workspace you do not own, inviting
into one, moving an account between them, and what a student keeps when they cannot move.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.types import Role
from app.identity import models as identity_models
from app.identity import repository, service
from app.projects import service as projects_service
from tests.factories import make_user, make_workspace

pytestmark = pytest.mark.module


async def _owned(db: AsyncSession, prof: identity_models.User) -> identity_models.Workspace:
    """The professor's own workspace, with ownership set the way bootstrap sets it."""
    workspace = await repository.get_workspace(db, prof.workspace_id)
    assert workspace is not None
    workspace.owner_id = prof.id
    await db.flush()
    return workspace


# ------------------------------------------------------------------ create, list, rename


async def test_a_created_workspace_is_owned_by_its_creator_and_empty(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    created = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)

    assert created.owner_id == prof.id
    assert created.id != prof_scope.workspace_id
    assert await repository.count_active_users(db, created.id) == 0, "nobody is in it yet"


async def test_the_list_carries_owned_workspaces_and_the_one_the_caller_is_in(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    # A professor invited as a colleague belongs to a workspace someone else owns, and would
    # otherwise not see their own on this list at all.
    source = prof_scope.workspace_id
    await _owned(db, prof)
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    listed = {workspace.id for workspace in await service.list_workspaces(db, prof_scope)}

    assert listed == {source, created.id}, "the one just left is still listed, to get back to"


async def test_a_professor_cannot_rename_a_workspace_they_do_not_own(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # The fixture workspace has no owner, which is the position a colleague is in: everything
    # ADR 0011 grants over the work, and nothing over the container.
    with pytest.raises(NotFoundError):
        await service.update_workspace(db, prof_scope, prof_scope.workspace_id, name="Renamed")


async def test_renaming_reports_absent_rather_than_forbidden_for_someone_elses_workspace(
    db: AsyncSession, prof_scope: Scope
) -> None:
    other = await make_workspace(db, name="Somebody Else's Lab")
    owner = await make_user(db, other, role=Role.PROF, email="other-prof@example.edu")
    other.owner_id = owner.id
    await db.flush()

    # AC-02: a 403 here would confirm the workspace exists.
    with pytest.raises(NotFoundError):
        await service.update_workspace(db, prof_scope, other.id, name="Mine now")


async def test_an_owner_renames_and_sets_the_timezone(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)

    updated = await service.update_workspace(
        db, prof_scope, prof_scope.workspace_id, name="Renamed", timezone="Europe/Berlin"
    )

    assert (updated.name, updated.timezone) == ("Renamed", "Europe/Berlin")


# ------------------------------------------------------------------ archiving


async def test_archiving_refuses_while_anyone_is_still_active(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)
    created = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    elsewhere = await repository.get_workspace(db, created.id)
    assert elsewhere is not None
    await make_user(db, elsewhere, role=Role.STUDENT, email="theirs@example.edu")

    with pytest.raises(ValidationError, match="active account"):
        await service.archive_workspace(db, prof_scope, created.id)


async def test_archiving_withdraws_the_invitations_left_pointing_at_it(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """An invited account is not an active one, so the count alone would let this through.

    The invitation link is a credential that sets a password and opens a session, so an archived
    workspace with a live one outstanding could still acquire its first member.
    """
    await _owned(db, prof)
    created = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    invited = await service.invite_user(
        db, prof_scope, email="new@example.edu", workspace_id=created.id
    )

    await service.archive_workspace(db, prof_scope, created.id)

    # Refused as an invalid token, which is what a revoked one is.
    with pytest.raises(ValidationError, match="invalid, used, or expired"):
        await service.accept_invitation(db, token=invited.token, password="a-good-enough-one")


async def test_the_workspace_your_account_lives_in_is_refused_by_name_not_by_count(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """The count message would be advice the professor cannot take.

    They are an active account in their own workspace and no route deactivates or removes them
    (ADR 0011), so "remove or deactivate them before archiving" names a step that does not exist.
    """
    await _owned(db, prof)

    with pytest.raises(ValidationError, match="nobody belongs to it"):
        await service.archive_workspace(db, prof_scope, prof_scope.workspace_id)


async def test_archiving_an_empty_workspace_closes_it(db: AsyncSession, prof_scope: Scope) -> None:
    created = await service.create_workspace(db, prof_scope, name="Retired Lab", join=False)

    archived = await service.archive_workspace(db, prof_scope, created.id)

    assert archived.archived_at is not None
    # Repeating it is a no-op rather than an error: the outcome asked for already holds.
    assert (await service.archive_workspace(db, prof_scope, created.id)).archived_at is not None


async def test_an_archived_workspace_refuses_new_invitations(
    db: AsyncSession, prof_scope: Scope
) -> None:
    created = await service.create_workspace(db, prof_scope, name="Retired Lab", join=False)
    await service.archive_workspace(db, prof_scope, created.id)

    with pytest.raises(ValidationError):
        await service.invite_user(db, prof_scope, email="late@example.edu", workspace_id=created.id)


# ------------------------------------------------------------------ the invitation names it


async def test_an_invitation_without_a_workspace_enrols_into_the_callers_own(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")

    user = await repository.get_user_by_email(db, "new@example.edu")
    assert user is not None
    assert user.workspace_id == prof_scope.workspace_id
    assert invited.invitation.email == "new@example.edu"


async def test_an_invitation_may_name_a_workspace_the_professor_owns(
    db: AsyncSession, prof_scope: Scope
) -> None:
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    await service.invite_user(db, prof_scope, email="new@example.edu", workspace_id=created.id)

    user = await repository.get_user_by_email(db, "new@example.edu")
    assert user is not None
    assert user.workspace_id == created.id, "the first account in a new workspace arrives this way"


async def test_an_invitation_cannot_name_a_workspace_the_professor_does_not_own(
    db: AsyncSession, prof_scope: Scope
) -> None:
    other = await make_workspace(db, name="Somebody Else's Lab")

    with pytest.raises(NotFoundError):
        await service.invite_user(db, prof_scope, email="new@example.edu", workspace_id=other.id)


async def test_an_address_belongs_to_one_workspace_across_all_of_them(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Re-inviting an existing account into another workspace is not how a student moves.
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    with pytest.raises(ConflictError):
        await service.invite_user(db, prof_scope, email=student_a.email, workspace_id=created.id)


# ------------------------------------------------------------------ what the schema still pins

# `users.workspace_id` is the parent of a composite foreign key on eight tables. Four of them —
# invitations, sessions, password_resets, notifications — hold identity records and cascade on
# update (ADR 0014), so an account with only those can move. The other four hold research history
# and do not, so a student who has written anything is refused by the database. The split is the
# rule "history stays in the workspace it was written in", enforced rather than remembered.


async def test_an_account_with_only_identity_records_can_move(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """An invitation alone no longer pins an account, which is what makes joining possible at all.

    Before ADR 0014 this raised: enrolment is invitation-only, so every account had an
    `invitations` row from creation and the update was refused for everyone.
    """
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    await service.invite_user(db, prof_scope, email="new@example.edu")
    user = await repository.get_user_by_email(db, "new@example.edu")
    assert user is not None

    user.workspace_id = destination.id
    await db.flush()

    assert user.workspace_id == destination.id


async def test_a_student_cannot_administer_workspaces(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    with pytest.raises(ForbiddenError):
        await service.create_workspace(db, student_a_scope, name="Mine")
    with pytest.raises(ForbiddenError):
        await service.list_workspaces(db, student_a_scope)


# ------------------------------------------------------------------ joining and leaving (ADR 0015)


async def test_a_professor_belongs_to_every_workspace_they_join(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """The point of ADR 0015: belonging is plural, and joining one does not leave another."""
    source = prof.workspace_id

    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    joined = {w.id for w in await repository.workspaces_joined_by(db, prof.id)}
    assert joined == {source, created.id}
    # And they are working in the new one, which is the singular half.
    assert prof.workspace_id == created.id


async def test_joining_one_they_already_belong_to_only_switches(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)
    source = prof.workspace_id
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    await service.join_workspace(db, await service.scope_for(db, prof), source)

    joined = {w.id for w in await repository.workspaces_joined_by(db, prof.id)}
    assert joined == {source, created.id}, "membership is unchanged"
    assert prof.workspace_id == source, "only which one they are working in moved"


async def test_a_workspace_keeps_its_member_while_they_work_elsewhere(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Archiving counts members, not the anchor column.

    Counting `users.workspace_id` would let a professor's workspace be archived out from under
    them the moment they went to work in another one.
    """
    source = prof.workspace_id

    await service.create_workspace(db, prof_scope, name="Vision Lab")

    assert await repository.count_active_users(db, source) == 1


async def test_leaving_removes_the_membership_and_empties_the_workspace(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)
    source = prof.workspace_id
    await service.create_workspace(db, prof_scope, name="Vision Lab")

    await service.leave_workspace(db, await service.scope_for(db, prof), source)

    assert await repository.count_active_users(db, source) == 0
    assert {w.id for w in await repository.workspaces_joined_by(db, prof.id)} != {source}


async def test_an_emptied_workspace_can_then_be_archived(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)
    source = prof.workspace_id
    await service.create_workspace(db, prof_scope, name="Vision Lab")
    await service.leave_workspace(db, await service.scope_for(db, prof), source)

    archived = await service.archive_workspace(db, await service.scope_for(db, prof), source)

    assert archived.archived_at is not None


async def test_leaving_your_only_workspace_is_refused(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """`users.workspace_id` is not nullable, so an account is always in at least one."""
    await _owned(db, prof)

    with pytest.raises(ValidationError, match="only workspace you belong to"):
        await service.leave_workspace(db, prof_scope, prof.workspace_id)


async def test_leaving_is_refused_while_it_would_strand_people(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """AUTH-01: a workspace with accounts in it is never left without an active professor."""
    await _owned(db, prof)
    source = prof.workspace_id
    await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)

    with pytest.raises(ValidationError, match="only professor"):
        await service.leave_workspace(db, prof_scope, source)


async def test_leaving_a_workspace_they_are_not_working_in(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Belonging and working in are different, so either can be left."""
    await _owned(db, prof)
    source = prof.workspace_id
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    await service.leave_workspace(db, await service.scope_for(db, prof), source)

    assert prof.workspace_id == created.id, "the anchor did not need to move"
    assert {w.id for w in await repository.workspaces_joined_by(db, prof.id)} == {created.id}


async def test_a_live_session_follows_the_account_rather_than_ending(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Creating a workspace must not sign the professor out of the one they are making it from."""
    opened = await service.start_session(db, user_id=prof.id)

    created = await service.create_workspace(db, prof_scope, name="Vision Lab")

    context = await service.resolve_session(db, token=opened.token)
    assert context is not None, "the session survived the move"
    assert context.scope.workspace_id == created.id


async def test_a_removed_student_stops_occupying_the_workspace(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Removal takes the membership, which is what the archive count reads."""
    assert await repository.count_active_users(db, prof.workspace_id) == 2

    await service.remove_student(db, prof_scope, student_a.id)

    assert await repository.count_active_users(db, prof.workspace_id) == 1


async def test_a_student_with_history_still_cannot_be_moved(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The four history foreign keys deliberately do not cascade (ADR 0014).

    This is the rule use_cases.md §2.1 records — history stays in the workspace it was written in —
    and it is the schema that enforces it, not a check anyone has to remember.
    """
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="theory"
    )
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )

    student_a.workspace_id = destination.id
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


# ------------------------------------------------------------------ moving a student


async def test_a_student_who_has_not_started_can_be_moved(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """The case this exists for: enrolled into the wrong workspace, before any work."""
    await _owned(db, prof)
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    await service.invite_user(db, prof_scope, email="new@example.edu")
    student = await repository.get_user_by_email(db, "new@example.edu")
    assert student is not None
    source = student.workspace_id

    moved = await service.move_student(db, prof_scope, student.id, workspace_id=destination.id)

    assert moved.workspace_id == destination.id
    joined = {w.id for w in await repository.workspaces_joined_by(db, student.id)}
    assert joined == {destination.id}, "membership and anchor move together"
    assert await repository.count_active_users(db, source) == 1, "only the professor is left"


async def test_a_student_who_has_started_cannot_be_moved(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The history foreign keys refuse, and the refusal is explained rather than raised raw."""
    await _owned(db, prof)
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="theory"
    )
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )

    student_id = student_a.id
    with pytest.raises(ValidationError, match="already done work"):
        await service.move_student(db, prof_scope, student_id, workspace_id=destination.id)

    # Re-read rather than trusting the in-session object: the savepoint rollback expires it.
    # That the read succeeds at all is the point — the transaction is still usable, which is what
    # the savepoint buys over letting the IntegrityError abort the request.
    after = await repository.get_user_by_id(db, student_id)
    assert after is not None
    assert after.workspace_id != destination.id


async def test_moving_ends_the_student_s_sessions(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """They did not ask to be moved, and what they can see has changed (AUTH-03)."""
    await _owned(db, prof)
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    await service.invite_user(db, prof_scope, email="new@example.edu")
    student = await repository.get_user_by_email(db, "new@example.edu")
    assert student is not None
    student.state = identity_models.UserState.ACTIVE
    await db.flush()
    opened = await service.start_session(db, user_id=student.id)

    await service.move_student(db, prof_scope, student.id, workspace_id=destination.id)

    assert await service.resolve_session(db, token=opened.token) is None


async def test_a_professor_is_not_moved_this_way(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    await _owned(db, prof)
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    colleague = await make_user(
        db,
        await repository.get_workspace(db, prof.workspace_id),  # type: ignore[arg-type]
        role=Role.PROF,
        email="colleague@example.edu",
    )

    with pytest.raises(ForbiddenError):
        await service.move_student(db, prof_scope, colleague.id, workspace_id=destination.id)


async def test_a_student_in_a_workspace_the_caller_does_not_administer_is_absent(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """AC-02 again: not forbidden, absent — a 404 must not confirm the account exists."""
    await _owned(db, prof)
    destination = await service.create_workspace(db, prof_scope, name="Vision Lab", join=False)
    elsewhere = await make_workspace(db, name="Somebody Else's Lab")
    theirs = await make_user(db, elsewhere, role=Role.STUDENT, email="theirs@example.edu")

    with pytest.raises(NotFoundError):
        await service.move_student(db, prof_scope, theirs.id, workspace_id=destination.id)


async def test_an_archived_workspace_leaves_the_list(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Archiving is the end of a workspace, so it stops being a row you can do anything with.

    It is empty of accounts by the time it can be archived and refuses invitations afterwards, so
    a listed archived workspace offers nothing but a name and a reason it cannot be used.
    """
    await _owned(db, prof)
    retired = await service.create_workspace(db, prof_scope, name="Retired Lab", join=False)
    assert retired.id in {w.id for w in await service.list_workspaces(db, prof_scope)}

    await service.archive_workspace(db, prof_scope, retired.id)

    assert retired.id not in {w.id for w in await service.list_workspaces(db, prof_scope)}


# ------------------------------------------------- reaching a workspace you belong to (ADR 0015)


async def test_a_colleague_can_switch_into_a_workspace_they_belong_to_but_do_not_own(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Joining one you already belong to moves the anchor, and that is how switching is spelled.

    The fixture workspace has no owner, which is the position a colleague is in. Gating the call on
    ownership made `Work here` unreachable for exactly the rows `list_workspaces` offers it on.
    """
    # Deliberately not `_owned`: the fixture workspace has no owner, which is the position a
    # colleague is in. Creating one takes the professor there, so coming back is the switch.
    colleague_workspace = prof_scope.workspace_id
    created = await service.create_workspace(db, prof_scope, name="Vision Lab")
    assert created.id != colleague_workspace
    home = await repository.get_workspace(db, colleague_workspace)
    assert home is not None and home.owner_id != prof.id, "the case is one they do not own"

    moved = await service.join_workspace(db, await service.scope_for(db, prof), colleague_workspace)

    assert moved.id == colleague_workspace
    refreshed = await service.scope_for(db, prof)
    assert refreshed.workspace_id == colleague_workspace, "the anchor followed the join"


async def test_a_colleague_can_read_a_workspace_they_belong_to_but_do_not_own(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    """Every row the list puts on the screen has to be readable, or the screen offers a 404."""
    listed = {workspace.id for workspace in await service.list_workspaces(db, prof_scope)}
    assert prof_scope.workspace_id in listed

    read = await service.get_workspace(db, prof_scope, prof_scope.workspace_id)

    assert read.id == prof_scope.workspace_id


async def test_reading_still_refuses_a_workspace_that_is_neither_owned_nor_joined(
    db: AsyncSession, prof_scope: Scope
) -> None:
    other = await make_workspace(db, name="Somebody Else's Lab")

    with pytest.raises(NotFoundError):
        await service.get_workspace(db, prof_scope, other.id)
    with pytest.raises(NotFoundError):
        await service.join_workspace(db, prof_scope, other.id)


async def test_belonging_does_not_grant_renaming(db: AsyncSession, prof_scope: Scope) -> None:
    """ADR 0012: ownership is the administration relation, and belonging is not ownership.

    The companion to the two tests above — widening what may be entered and read must not widen
    what may be administered.
    """
    with pytest.raises(NotFoundError):
        await service.update_workspace(db, prof_scope, prof_scope.workspace_id, name="Renamed")
