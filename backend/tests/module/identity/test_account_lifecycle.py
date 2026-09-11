"""AUTH-01/AUTH-03: deactivation, role changes, profiles, and the access epoch.

AUTH-03 requires that removing access invalidates subsequent access, including cached answers.
The epoch on the workspace is what later modules compare their cached answers against.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.errors import ForbiddenError, NotFoundError
from app.core.types import Role
from app.identity import models, service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _epoch(db: AsyncSession, workspace_id: object) -> int:
    return (
        await db.execute(
            select(models.Workspace.access_epoch).where(models.Workspace.id == workspace_id)
        )
    ).scalar_one()


async def test_deactivation_revokes_existing_sessions_immediately(
    db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    assert await service.resolve_session(db, token=logged_in.token) is not None

    await service.deactivate_user(db, prof_scope, student_a.id)

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_deactivation_advances_the_access_epoch(
    db: AsyncSession, workspace: models.Workspace, prof_scope: Scope, student_a: models.User
) -> None:
    before = await _epoch(db, workspace.id)

    await service.deactivate_user(db, prof_scope, student_a.id)

    assert await _epoch(db, workspace.id) == before + 1


async def test_deactivation_records_the_state_and_time(
    db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    user = await service.deactivate_user(db, prof_scope, student_a.id)

    assert user.state is models.UserState.DEACTIVATED
    assert user.deactivated_at is not None


async def test_deactivating_an_already_deactivated_user_is_idempotent(
    db: AsyncSession, workspace: models.Workspace, prof_scope: Scope, student_a: models.User
) -> None:
    await service.deactivate_user(db, prof_scope, student_a.id)
    epoch = await _epoch(db, workspace.id)

    user = await service.deactivate_user(db, prof_scope, student_a.id)

    assert user.state is models.UserState.DEACTIVATED
    assert await _epoch(db, workspace.id) == epoch, "no second epoch bump, no second audit storm"


async def test_a_student_cannot_deactivate_another_student(
    db: AsyncSession, student_a_scope: Scope, student_b: models.User
) -> None:
    with pytest.raises(ForbiddenError):
        await service.deactivate_user(db, student_a_scope, student_b.id)


async def test_the_professor_cannot_deactivate_their_own_account(
    db: AsyncSession, prof_scope: Scope, prof: models.User
) -> None:
    # Locking the only professor out is what the break-glass runbook exists to undo (AUTH-01).
    with pytest.raises(ForbiddenError):
        await service.deactivate_user(db, prof_scope, prof.id)


async def test_reactivation_restores_login(
    db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    await service.deactivate_user(db, prof_scope, student_a.id)

    user = await service.reactivate_user(db, prof_scope, student_a.id)

    assert user.state is models.UserState.ACTIVE
    assert user.deactivated_at is None
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    assert logged_in.user.id == student_a.id


async def test_only_the_professor_changes_roles(
    db: AsyncSession, workspace: models.Workspace, prof_scope: Scope, student_a: models.User
) -> None:
    before = await _epoch(db, workspace.id)

    user = await service.set_role(db, prof_scope, student_a.id, Role.PROF)

    assert user.role is Role.PROF
    assert await _epoch(db, workspace.id) == before + 1, "a role change changes what is visible"


async def test_a_student_cannot_change_their_own_role(
    db: AsyncSession, student_a_scope: Scope, student_a: models.User
) -> None:
    with pytest.raises(ForbiddenError):
        await service.set_role(db, student_a_scope, student_a.id, Role.PROF)


async def test_a_user_updates_their_own_profile(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    user = await service.update_profile(db, student_a_scope, display_name="Renamed", locale="vi")

    assert user.display_name == "Renamed"
    assert user.locale == "vi"


async def test_a_user_outside_the_workspace_is_not_found(
    db: AsyncSession, prof_scope: Scope
) -> None:
    from tests.factories import make_user, make_workspace

    other_workspace = await make_workspace(db, name="Another Lab")
    outsider = await make_user(db, other_workspace)

    with pytest.raises(NotFoundError):
        await service.deactivate_user(db, prof_scope, outsider.id)


async def test_account_changes_are_audited(
    db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    await service.deactivate_user(db, prof_scope, student_a.id)
    await service.reactivate_user(db, prof_scope, student_a.id)
    await service.set_role(db, prof_scope, student_a.id, Role.PROF)

    actions = set(
        (await db.execute(select(AuditEvent.action).where(AuditEvent.target_id == student_a.id)))
        .scalars()
        .all()
    )
    assert {"user.deactivated", "user.reactivated", "user.role_changed"} <= actions
