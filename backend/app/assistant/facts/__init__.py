"""Deterministic fact functions (QA-02, architecture §11).

Importing this package registers every function. The registry is what the router may name and the
service may call: a name the router invents is dropped rather than approximated, because answering
a near-neighbour of the question asked is worse than saying nothing.
"""

from __future__ import annotations

from app.assistant.facts import members, obligations, reports, scores, sources  # noqa: F401
from app.assistant.facts.base import (
    Citation,
    Fact,
    FactFunction,
    FactQuery,
    available,
    fact,
    get,
    run,
)

__all__ = [
    "Citation",
    "Fact",
    "FactFunction",
    "FactQuery",
    "available",
    "fact",
    "get",
    "run",
]
