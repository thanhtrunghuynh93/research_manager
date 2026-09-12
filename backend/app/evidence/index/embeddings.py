"""Turning chunk text into vectors, without knowing who makes them.

docs/repo_layout.md §3.1 sketched this module as calling `ai.gateway.embed` directly, but §3.3
forbids `app.evidence` from importing `app.ai` — and the contract is the one worth keeping: the
index should not care which provider produces a vector, and a project marked `ai_restricted` must
be able to skip the provider entirely (architecture §10).

So the embedder is registered rather than imported. `app.ai` supplies the gateway-backed one at
start-up; tests and restricted projects supply a deterministic local one.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small; architecture §5.7


@dataclass(frozen=True, slots=True)
class EmbedContext:
    """Who this embedding is for, so an embedder that costs money can account for it.

    `app.evidence` may not import `app.ai` (docs/repo_layout.md §3.3), so the index cannot write a
    cost-ledger row itself. It can say which workspace and project it is indexing for and leave the
    accounting to whoever produces the vectors — the local embedder ignores this entirely.
    """

    workspace_id: UUID | None = None
    project_id: UUID | None = None
    session: AsyncSession | None = None


class Embedder(Protocol):
    dimensions: int

    async def embed(
        self, texts: list[str], *, context: EmbedContext | None = None
    ) -> list[list[float]]: ...


class DeterministicEmbedder:
    """A hash-based embedder: no provider, no network, same text always the same vector.

    It is not semantic. It exists so the index, the permission filter, and the citation path can be
    exercised without sending research text anywhere, and so a restricted project still gets rows
    it can retrieve lexically (architecture §10).
    """

    dimensions = EMBEDDING_DIMENSIONS

    async def embed(
        self, texts: list[str], *, context: EmbedContext | None = None
    ) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.blake2b(text.strip().lower().encode(), digest_size=64).digest()
        raw = [(digest[index % len(digest)] - 128) / 128 for index in range(self.dimensions)]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]


_embedder: Embedder = DeterministicEmbedder()


def register_embedder(embedder: Embedder) -> Embedder:
    """Called once at start-up by whoever owns the model provider."""
    global _embedder
    _embedder = embedder
    return embedder


def current_embedder() -> Embedder:
    return _embedder


LOCAL_EMBEDDER: Embedder = DeterministicEmbedder()


def local_embedder() -> Embedder:
    """The embedder that reaches nobody, for material that must not leave the host.

    Kept separate from `_embedder` so a caller can ask for it explicitly, and so its vectors are
    cached under their own key rather than mixed into the registered embedder's space.
    """
    return LOCAL_EMBEDDER


# sha256(text) + model keyed, as the architecture's cost control requires: an unchanged chunk is
# never re-embedded (architecture §10).
_cache: dict[tuple[str, str], list[float]] = {}
CACHE_LIMIT = 10_000


async def embed_texts(
    texts: list[str],
    *,
    embedder: Embedder | None = None,
    context: EmbedContext | None = None,
) -> list[list[float]]:
    active = embedder or _embedder
    model = type(active).__name__
    missing = [text for text in texts if (model, _key(text)) not in _cache]
    if missing:
        fresh = await active.embed(missing, context=context)
        for text, vector in zip(missing, fresh, strict=True):
            if len(_cache) >= CACHE_LIMIT:
                _cache.clear()
            _cache[(model, _key(text))] = vector
    return [_cache[(model, _key(text))] for text in texts]


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def clear_cache() -> None:
    _cache.clear()
