"""Authorization core: the per-request Scope and the visible_to() predicate registry.

Every module registers one predicate builder per aggregate in its policies.py:

    @register_policy(WeeklyReport)
    def _(scope: Scope) -> ColumnElement[bool]:
        return true() if scope.role is Role.PROF else WeeklyReport.student_id == scope.user_id

Repository functions then write  select(WeeklyReport).where(visible_to(scope, WeeklyReport)).
Search, downloads, and AI retrieval reuse the same predicates (architecture §6.1).

`Scope.within(column)` is the workspace half of every one of those predicates, and the only place
that compares against the read-set (ADR 0016).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.errors import ForbiddenError
from app.core.types import ActorKind, Role

PolicyBuilder = Callable[["Scope"], ColumnElement[bool]]
_POLICIES: dict[type[Any], PolicyBuilder] = {}

# A student's Scope carries the projects they are currently a member of. identity resolves the
# session but sits below projects in the layer order, so projects registers the loader here.
ProjectIdsLoader = Callable[[AsyncSession, UUID, UUID], Awaitable[frozenset[UUID]]]
_project_ids_loader: ProjectIdsLoader | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    # Where a write goes, and the workspace a request is "in". Always one, always a member of
    # `workspace_ids`. Creating a project, configuring a calendar, inviting someone: each needs
    # exactly one destination, and this is it.
    workspace_id: UUID
    user_id: UUID
    role: Role
    project_ids: frozenset[UUID]
    access_epoch: int
    # What a read may see: every workspace this account belongs to (ADR 0016). A student has one
    # membership, so for them this is `{workspace_id}` and nothing about their access changed.
    # Empty means "not set" and is filled in by __post_init__ with `{workspace_id}`, which keeps
    # a hand-built Scope — a job's, a test's — single-workspace unless it says otherwise.
    workspace_ids: frozenset[UUID] = frozenset()
    # The epoch of every workspace in `workspace_ids`, as (workspace_id, epoch) pairs.
    # `access_epoch` above stays the anchor's, because a snapshot is built for one workspace and is
    # right to key off it. A *read* that spans has to be validated against everything it spanned,
    # or ending a membership in one workspace leaves an answer resting on it cached under another
    # (ADR 0016, AUTH-03). Empty means "not set", filled in by __post_init__ as `workspace_ids` is.
    access_epochs: frozenset[tuple[UUID, int]] = frozenset()
    # True when a scheduled task built this Scope by borrowing a user's identity rather than
    # resolving a session. The identity is a lens, not an author: see `audit_actor` (ADR 0011).
    is_system: bool = False

    def __post_init__(self) -> None:
        if not self.workspace_ids:
            object.__setattr__(self, "workspace_ids", frozenset({self.workspace_id}))
        if not self.access_epochs:
            object.__setattr__(
                self, "access_epochs", frozenset({(self.workspace_id, self.access_epoch)})
            )

    def within(self, column: Any) -> ColumnElement[bool]:
        """The workspace test every visibility predicate is built on.

        One place rather than thirty-three, because widening what a read may see is the single
        most consequential change anyone can make to this system, and it should be visible in one
        diff rather than spread across every module's policies.py.
        """
        predicate: ColumnElement[bool] = column.in_(self.workspace_ids)
        return predicate

    @property
    def is_prof(self) -> bool:
        return self.role is Role.PROF

    @property
    def audit_actor(self) -> tuple[UUID | None, ActorKind]:
        """Who to record as the actor of a write made under this Scope.

        A system scope borrows a professor to inherit professor visibility. With one professor per
        workspace the borrowed identity was also the right author; with several it is whichever row
        sorted first, so attributing the write to them would be a lie a reader cannot detect.
        """
        if self.is_system:
            return None, ActorKind.SYSTEM
        return self.user_id, ActorKind.USER

    def require_prof(self) -> None:
        if not self.is_prof:
            raise ForbiddenError("professor role required")

    def require_project(self, project_id: UUID) -> None:
        if not self.is_prof and project_id not in self.project_ids:
            raise ForbiddenError("not a member of this project")


def register_policy(model: type[Any]) -> Callable[[PolicyBuilder], PolicyBuilder]:
    def decorator(builder: PolicyBuilder) -> PolicyBuilder:
        if model in _POLICIES:
            raise RuntimeError(f"visibility policy already registered for {model.__name__}")
        _POLICIES[model] = builder
        return builder

    return decorator


def visible_to(scope: Scope, model: type[Any]) -> ColumnElement[bool]:
    try:
        builder = _POLICIES[model]
    except KeyError as exc:  # fail closed: an aggregate without a policy cannot be queried
        raise RuntimeError(f"no visibility policy registered for {model.__name__}") from exc
    return builder(scope)


def registered_models() -> frozenset[type[Any]]:
    return frozenset(_POLICIES)


def register_project_ids_loader(loader: ProjectIdsLoader) -> ProjectIdsLoader:
    global _project_ids_loader
    _project_ids_loader = loader
    return loader


async def load_project_ids(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> frozenset[UUID]:
    """Empty until the projects module registers its loader: no memberships, no project access."""
    if _project_ids_loader is None:
        return frozenset()
    return await _project_ids_loader(session, workspace_id, user_id)
