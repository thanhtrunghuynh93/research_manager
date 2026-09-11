"""Authorization core: the per-request Scope and the visible_to() predicate registry.

Every module registers one predicate builder per aggregate in its policies.py:

    @register_policy(WeeklyReport)
    def _(scope: Scope) -> ColumnElement[bool]:
        return true() if scope.role is Role.PROF else WeeklyReport.student_id == scope.user_id

Repository functions then write  select(WeeklyReport).where(visible_to(scope, WeeklyReport)).
Search, downloads, exports, and AI retrieval reuse the same predicates (architecture §6.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.errors import ForbiddenError
from app.core.types import Role

PolicyBuilder = Callable[["Scope"], ColumnElement[bool]]
_POLICIES: dict[type[Any], PolicyBuilder] = {}

# A student's Scope carries the projects they are currently a member of. identity resolves the
# session but sits below projects in the layer order, so projects registers the loader here.
ProjectIdsLoader = Callable[[AsyncSession, UUID, UUID], Awaitable[frozenset[UUID]]]
_project_ids_loader: ProjectIdsLoader | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    workspace_id: UUID
    user_id: UUID
    role: Role
    project_ids: frozenset[UUID]
    access_epoch: int

    @property
    def is_prof(self) -> bool:
        return self.role is Role.PROF

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
