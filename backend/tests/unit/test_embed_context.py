"""The index tells the embedder who to bill; whether it bills is the embedder's business.

`app.evidence` may not import `app.ai` (docs/repo_layout.md §3.3), so the index cannot write a
ledger row itself. What it can do is pass the workspace and project it is indexing for, which is
enough for a gateway-backed embedder to account for the call and for a local one to ignore it.
"""

from __future__ import annotations

import pytest

from app.core.ids import uuid7
from app.evidence.index.embeddings import (
    DeterministicEmbedder,
    EmbedContext,
    clear_cache,
    embed_texts,
)

pytestmark = pytest.mark.unit


class _Recorder:
    dimensions = 4

    def __init__(self) -> None:
        self.seen: list[EmbedContext | None] = []

    async def embed(
        self, texts: list[str], *, context: EmbedContext | None = None
    ) -> list[list[float]]:
        self.seen.append(context)
        return [[0.5] * self.dimensions for _ in texts]


async def test_the_context_reaches_the_embedder() -> None:
    clear_cache()
    recorder = _Recorder()
    workspace_id, project_id = uuid7(), uuid7()

    await embed_texts(
        [f"a chunk {uuid7()}"],
        embedder=recorder,
        context=EmbedContext(workspace_id=workspace_id, project_id=project_id),
    )

    assert recorder.seen[0] is not None
    assert recorder.seen[0].workspace_id == workspace_id
    assert recorder.seen[0].project_id == project_id


async def test_an_embedder_that_ignores_the_context_still_works() -> None:
    clear_cache()
    vectors = await DeterministicEmbedder().embed(
        ["text"], context=EmbedContext(workspace_id=uuid7())
    )

    assert len(vectors) == 1


async def test_a_cached_text_does_not_reach_the_embedder_a_second_time() -> None:
    clear_cache()
    recorder = _Recorder()
    text = f"a chunk {uuid7()}"

    await embed_texts([text], embedder=recorder)
    await embed_texts([text], embedder=recorder)

    assert len(recorder.seen) == 1
