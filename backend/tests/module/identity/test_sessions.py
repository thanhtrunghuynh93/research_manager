"""AUTH-01/AUTH-03: login, session resolution, expiry, and logout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import UnauthenticatedError
from app.core.types import ActorKind, Role
from app.identity import models, security, service
from tests.factories import DEFAULT_PASSWORD, make_user, make_workspace

pytestmark = pytest.mark.module


async def test_login_returns_a_session_token_that_resolves_to_a_scope(
    db: AsyncSession, workspace: models.Workspace, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    context = await service.resolve_session(db, token=logged_in.token)
    assert context is not None
    assert context.scope.user_id == student_a.id
    assert context.scope.workspace_id == workspace.id
    assert context.scope.role is Role.STUDENT
    assert context.scope.access_epoch == workspace.access_epoch
    assert context.scope.project_ids == frozenset(), "memberships arrive with the projects module"


async def test_login_is_case_insensitive_on_the_email(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email.upper(), password=DEFAULT_PASSWORD)
    assert logged_in.user.id == student_a.id


async def test_the_wrong_password_is_rejected(db: AsyncSession, student_a: models.User) -> None:
    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=student_a.email, password="not the password")


async def test_an_unknown_email_is_rejected_without_revealing_anything(db: AsyncSession) -> None:
    with pytest.raises(UnauthenticatedError) as raised:
        await service.login(db, email="nobody@example.edu", password=DEFAULT_PASSWORD)
    assert "nobody@example.edu" not in raised.value.detail


async def test_an_invited_user_cannot_log_in_before_accepting(
    db: AsyncSession, workspace: models.Workspace
) -> None:
    await make_user(db, workspace, state=models.UserState.INVITED, password=None)
    invited = (
        await db.execute(select(models.User).where(models.User.state == models.UserState.INVITED))
    ).scalar_one()

    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=invited.email, password=DEFAULT_PASSWORD)


async def test_a_deactivated_user_cannot_log_in(
    db: AsyncSession, workspace: models.Workspace
) -> None:
    user = await make_user(db, workspace, state=models.UserState.DEACTIVATED)

    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=user.email, password=DEFAULT_PASSWORD)


async def test_logout_revokes_the_session(db: AsyncSession, student_a: models.User) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    await service.logout(db, token=logged_in.token)

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_logout_of_an_unknown_token_is_a_no_op(db: AsyncSession) -> None:
    await service.logout(db, token="not-a-real-token")


async def test_a_session_idle_for_more_than_twelve_hours_stops_resolving(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == security.hash_token(logged_in.token))
        .values(last_seen_at=now() - timedelta(hours=12, minutes=1))
    )

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_a_session_past_its_absolute_lifetime_stops_resolving(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == security.hash_token(logged_in.token))
        .values(expires_at=now() - timedelta(seconds=1))
    )

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_resolving_a_session_refreshes_last_seen_at_at_most_once_a_minute(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    token_hash = security.hash_token(logged_in.token)
    stale = now() - timedelta(minutes=5)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == token_hash)
        .values(last_seen_at=stale)
    )

    await service.resolve_session(db, token=logged_in.token)
    refreshed = (
        await db.execute(
            select(models.Session.last_seen_at).where(models.Session.token_hash == token_hash)
        )
    ).scalar_one()
    assert refreshed > stale

    await service.resolve_session(db, token=logged_in.token)
    unchanged = (
        await db.execute(
            select(models.Session.last_seen_at).where(models.Session.token_hash == token_hash)
        )
    ).scalar_one()
    assert unchanged == refreshed, "a second request within the minute writes nothing"


async def test_an_unknown_session_token_resolves_to_nothing(db: AsyncSession) -> None:
    assert await service.resolve_session(db, token="not-a-real-token") is None


async def test_only_the_digest_of_a_session_token_is_stored(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    stored = (await db.execute(select(models.Session.token_hash))).scalars().all()
    assert stored == [security.hash_token(logged_in.token)]
    assert logged_in.token not in stored


# ---------------------------------------------------------------- mass revocation
#
# docs/runbooks/rotate-secrets.md sends an operator here after a suspected leak, and nothing else
# in the system ends every session at once. Rotating a configuration value does not — there is no
# signing key to rotate (app/identity/security.py) — so these are the tests standing between that
# runbook and a step that silently does nothing, which is what it used to be.


async def test_revoke_all_sessions_ends_every_live_session(
    db: AsyncSession, student_a: models.User, student_b: models.User
) -> None:
    one = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    two = await service.login(db, email=student_b.email, password=DEFAULT_PASSWORD)

    assert await service.revoke_all_sessions(db) == 2

    assert await service.resolve_session(db, token=one.token) is None
    assert await service.resolve_session(db, token=two.token) is None


async def test_revoke_all_sessions_reaches_every_workspace(
    db: AsyncSession, student_a: models.User
) -> None:
    other_workspace = await make_workspace(db, name="Second Lab")
    other_user = await make_user(db, other_workspace)
    here = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    there = await service.login(db, email=other_user.email, password=DEFAULT_PASSWORD)

    assert await service.revoke_all_sessions(db) == 2

    assert await service.resolve_session(db, token=here.token) is None
    assert await service.resolve_session(db, token=there.token) is None


async def test_revoke_all_sessions_writes_one_system_audit_row_per_workspace(
    db: AsyncSession, workspace: models.Workspace, student_a: models.User
) -> None:
    other_workspace = await make_workspace(db, name="Second Lab")
    other_user = await make_user(db, other_workspace)
    await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await service.login(db, email=other_user.email, password=DEFAULT_PASSWORD)

    await service.revoke_all_sessions(db)

    events = (
        (
            await db.execute(
                select(AuditEvent).where(AuditEvent.action == "identity.revoke_all_sessions")
            )
        )
        .scalars()
        .all()
    )
    assert {event.workspace_id for event in events} == {workspace.id, other_workspace.id}
    assert all(event.actor_kind is ActorKind.SYSTEM for event in events)
    assert all(event.actor_id is None for event in events)
    assert all(event.after == {"revoked": 1} for event in events)


async def test_revoke_all_sessions_counts_only_the_sessions_it_ended(
    db: AsyncSession, student_a: models.User, student_b: models.User
) -> None:
    """A session already logged out is not re-revoked, so the printed count is the true one."""
    gone = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await service.login(db, email=student_b.email, password=DEFAULT_PASSWORD)
    await service.logout(db, token=gone.token)

    assert await service.revoke_all_sessions(db) == 1


async def test_revoke_all_sessions_leaves_pending_invitations_alone(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The runbook promises sessions and says invitations are separate; hold it to that."""
    invited = await service.invite_user(db, prof_scope, email="new@example.edu", role=Role.STUDENT)

    await service.revoke_all_sessions(db)

    user = await service.accept_invitation(db, token=invited.token, password=DEFAULT_PASSWORD)
    assert user.state is models.UserState.ACTIVE
