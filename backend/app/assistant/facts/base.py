"""What a fact is, and the registry of the functions that produce one (QA-02, architecture §11).

The rule this module exists to enforce: a number the professor acts on is computed in SQL, not
written by a model. "How many reports are missing?" has an answer in the obligations table, and the
only honest way to give it is to read that table and render the result. A model asked to count will
sometimes be right, which is worse than being reliably absent.

Every fact carries the function that produced it and the instant it was true, because "three
missing" is not a fact without an as-of (AC-15).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope


@dataclass(frozen=True, slots=True)
class Citation:
    """Where a row in a fact came from, in the form the answer contract needs (QA-03)."""

    source_kind: str
    source_id: UUID
    source_version: str = ""
    locator: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class Fact:
    """One computed answer, with everything needed to show its working."""

    name: str
    label: str
    value: Any
    as_of: datetime
    rows: list[dict[str, Any]] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    note: str = ""

    def render(self) -> str:
        return f"{self.label}: {self.value} (as of {self.as_of.isoformat()})"


@dataclass(frozen=True, slots=True)
class FactQuery:
    """The arguments every fact function accepts. Unused ones are simply ignored.

    One shape rather than one signature per function: the router names a function and supplies
    entities, and the caller must be able to dispatch without knowing which arguments that
    particular function reads.
    """

    scope: Scope
    as_of: datetime
    student_id: UUID | None = None
    project_id: UUID | None = None
    period_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


FactFunction = Callable[[AsyncSession, FactQuery], Awaitable[Fact | None]]

_REGISTRY: dict[str, FactFunction] = {}


def fact(name: str) -> Callable[[FactFunction], FactFunction]:
    def decorator(function: FactFunction) -> FactFunction:
        if name in _REGISTRY:
            raise RuntimeError(f"a fact function named {name!r} is already registered")
        _REGISTRY[name] = function
        return function

    return decorator


def available() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str) -> FactFunction | None:
    """None for an unknown name.

    The router is a model and may invent a function name. An unknown name is dropped rather than
    guessed at, because a near-match would answer a different question than the one asked.
    """
    return _REGISTRY.get(name)


async def run(session: AsyncSession, name: str, query: FactQuery) -> Fact | None:
    function = _REGISTRY.get(name)
    if function is None:
        return None
    return await function(session, query)
