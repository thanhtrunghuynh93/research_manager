"""Authorization core: the per-request Scope and the visible_to() predicate registry.

Every module registers one predicate builder per aggregate in its policies.py:

    @register_policy(WeeklyReport)
    def _(scope: Scope) -> ColumnElement[bool]:
        return true() if scope.role is Role.PROF else WeeklyReport.student_id == scope.user_id

Repository functions then write  select(WeeklyReport).where(visible_to(scope, WeeklyReport)).
Search, downloads, exports, and AI retrieval reuse the same predicates (architecture §6.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.sql import ColumnElement

from app.core.errors import ForbiddenError
from app.core.types import Role

PolicyBuilder = Callable[["Scope"], ColumnElement[bool]]
_POLICIES: dict[type[Any], PolicyBuilder] = {}


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
