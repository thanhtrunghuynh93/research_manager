"""ADR 0011: two professors manage the students equally, and neither manages the other.

The visibility predicates were already role-based, so the sharing half of this needs asserting
rather than building — a later narrowing of "professor-only" to "this professor" would break these.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.errors import ConflictError, ForbiddenError, ValidationError
from app.core.types import ActorKind, Role
from app.identity import models, service
from tests.factories import DEFAULT_PASSWORD, make_user

pytestmark = pytest.mark.module


@pytest.fixture
async def colleague(
    db: AsyncSession, workspace: models.Workspace, prof: models.User
) -> models.User:
    """The second professor. Depends on `prof` so requesting it always yields a co-equal pair —
    a lone "colleague" would be the single-professor workspace under a different name."""
    return await make_user(db, workspace, role=Role.PROF, email="colleague@example.edu")


@pytest.fixture
async def colleague_scope(db: AsyncSession, colleague: models.User) -> Scope:
    return await service.scope_for(db, colleague)


# ---------------------------------------------------------------- equal over students


async def test_a_colleague_may_invite_a_student(db: AsyncSession, colleague_scope: Scope) -> None:
    invited = await service.invite_user(db, colleague_scope, email="new@example.edu")

    assert invited.invitation.role is Role.STUDENT


async def test_a_professor_may_invite_a_colleague_as_a_professor(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The only way a professor is added short of bootstrap or break-glass (ADR 0011)."""
    invited = await service.invite_user(db, prof_scope, email="second@example.edu", role=Role.PROF)
    accepted = await service.accept_invitation(db, token=invited.token, password=DEFAULT_PASSWORD)

    assert accepted.role is Role.PROF


async def test_either_professor_may_remove_a_student(
    db: AsyncSession, colleague_scope: Scope, student_a: models.User
) -> None:
    removed = await service.remove_student(db, colleague_scope, student_a.id)

    assert removed.state is models.UserState.DEACTIVATED


async def test_both_professors_scope_the_same_workspace(
    db: AsyncSession, prof_scope: Scope, colleague_scope: Scope
) -> None:
    """Every visibility predicate keys on the role, so co-supervisors see one workspace, not two."""
    assert colleague_scope.is_prof
    assert colleague_scope.workspace_id == prof_scope.workspace_id
    assert colleague_scope.user_id != prof_scope.user_id


# ---------------------------------------------------------------- unequal over each other


async def test_neither_professor_can_eject_the_other_through_the_service(
    db: AsyncSession, prof_scope: Scope, colleague_scope: Scope, prof: models.User
) -> None:
    with pytest.raises(ForbiddenError):
        await service.deactivate_user(db, colleague_scope, prof.id)
    with pytest.raises(ForbiddenError):
        await service.remove_student(db, colleague_scope, prof.id)


async def test_break_glass_demotes_a_professor(db: AsyncSession, colleague: models.User) -> None:
    user = await service.demote_professor(db, email=colleague.email)

    assert user.role is Role.STUDENT


async def test_break_glass_deactivates_a_professor(
    db: AsyncSession, colleague: models.User
) -> None:
    user = await service.deactivate_professor(db, email=colleague.email)

    assert user.state is models.UserState.DEACTIVATED


async def test_break_glass_records_the_system_as_the_actor(
    db: AsyncSession, colleague: models.User
) -> None:
    await service.demote_professor(db, email=colleague.email)

    event = (
        await db.execute(
            select(AuditEvent).where(
                AuditEvent.target_id == colleague.id,
                AuditEvent.action == "identity.break_glass_demote",
            )
        )
    ).scalar_one()
    assert event.actor_kind is ActorKind.SYSTEM
    assert event.actor_id is None


@pytest.mark.parametrize("command", ["demote_professor", "deactivate_professor"])
async def test_the_last_professor_cannot_be_removed(
    db: AsyncSession, prof: models.User, command: str
) -> None:
    """The invariant the self-action guards used to provide by accident (ADR 0011)."""
    with pytest.raises(ConflictError):
        await getattr(service, command)(db, email=prof.email)


async def test_break_glass_refuses_an_account_that_is_not_a_professor(
    db: AsyncSession, student_a: models.User
) -> None:
    with pytest.raises(ValidationError):
        await service.demote_professor(db, email=student_a.email)


async def test_demotion_is_allowed_while_another_professor_remains(
    db: AsyncSession, workspace: models.Workspace, prof: models.User, colleague: models.User
) -> None:
    await service.demote_professor(db, email=colleague.email)

    remaining = await service.professor_ids(db, workspace.id)
    assert remaining == [prof.id]


# ---------------------------------------------------------------- the borrowed system identity


async def test_the_system_scope_is_stable_and_marked(
    db: AsyncSession, workspace: models.Workspace, prof: models.User, colleague: models.User
) -> None:
    """With several professors the borrowed identity must not depend on row order, and must not be
    mistaken for an author: `audit_actor` reports the system instead (ADR 0011)."""
    first = await service.system_scope(db, workspace.id)
    second = await service.system_scope(db, workspace.id)

    assert first.user_id == second.user_id
    assert first.is_system
    assert first.audit_actor == (None, ActorKind.SYSTEM)


async def test_a_request_scope_is_its_own_author(db: AsyncSession, prof_scope: Scope) -> None:
    assert prof_scope.audit_actor == (prof_scope.user_id, ActorKind.USER)


async def test_a_write_under_the_system_scope_is_audited_as_the_system(
    db: AsyncSession, workspace: models.Workspace, prof: models.User
) -> None:
    """The property above is worth nothing unless `write_audit` actually consults it.

    It did not. Nineteen of the twenty call sites reached past `audit_actor` to `scope.user_id`
    and let `actor_kind` default to `user`, so every write a periodic task made was recorded as a
    decision by whichever professor sorted first — a claim no reader of the table could check.
    Found on the first production deploy, where the row named an id that was not a user at all.
    """
    scope = await service.system_scope(db, workspace.id)

    await service.set_ai_budgets(db, scope, {"monthly_usd": "100.00", "project_monthly_usd": {}})
    await db.flush()

    event = (
        (
            await db.execute(
                select(AuditEvent).where(AuditEvent.action == "workspace.ai_budgets_set")
            )
        )
        .scalars()
        .one()
    )
    assert event.actor_kind is ActorKind.SYSTEM
    assert event.actor_id is None


async def test_a_write_under_a_request_scope_still_names_its_author(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The other side of the boundary: a professor acting through the API is the author."""
    await service.set_ai_budgets(db, prof_scope, {"monthly_usd": "5.00", "project_monthly_usd": {}})
    await db.flush()

    event = (
        (
            await db.execute(
                select(AuditEvent).where(AuditEvent.action == "workspace.ai_budgets_set")
            )
        )
        .scalars()
        .one()
    )
    assert event.actor_kind is ActorKind.USER
    assert event.actor_id == prof_scope.user_id


async def test_an_explicit_actor_alongside_a_scope_is_refused(
    db: AsyncSession, workspace: models.Workspace, prof: models.User
) -> None:
    """The bug was a caller overriding the scope's answer, so the signature refuses to merge them.

    Allowing both and letting the explicit one win is how this regresses: it reads as a harmless
    convenience at the call site and silently turns a system write back into a person's.
    """
    from app.core.audit import write_audit

    scope = await service.system_scope(db, workspace.id)

    with pytest.raises(ValueError, match="either a scope or an explicit actor"):
        write_audit(
            db,
            scope=scope,
            actor_id=prof.id,
            action="workspace.ai_budgets_set",
            target_table="workspaces",
            target_id=workspace.id,
        )


async def test_an_audit_row_needs_a_workspace_from_somewhere(db: AsyncSession) -> None:
    from app.core.audit import write_audit

    with pytest.raises(ValueError, match="needs a workspace_id"):
        write_audit(db, action="x", target_table="workspaces", target_id=None)
