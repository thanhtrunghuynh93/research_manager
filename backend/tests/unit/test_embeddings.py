"""The index must work without a model provider, and never re-embed what has not changed."""

from __future__ import annotations

import pytest

from app.evidence.index import embeddings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    embeddings.clear_cache()


async def test_the_default_embedder_needs_no_provider() -> None:
    vectors = await embeddings.embed_texts(["the baseline reproduces"])

    assert len(vectors) == 1
    assert len(vectors[0]) == embeddings.EMBEDDING_DIMENSIONS


async def test_the_same_text_always_gives_the_same_vector() -> None:
    first = await embeddings.embed_texts(["identical text"])
    embeddings.clear_cache()
    second = await embeddings.embed_texts(["identical text"])

    assert first == second


async def test_vectors_are_normalised() -> None:
    [vector] = await embeddings.embed_texts(["anything at all"])

    length = sum(value * value for value in vector) ** 0.5
    assert 0.99 < length < 1.01


async def test_an_unchanged_chunk_is_not_embedded_twice() -> None:
    calls: list[list[str]] = []

    class Counting:
        dimensions = embeddings.EMBEDDING_DIMENSIONS

        async def embed(
            self, texts: list[str], *, context: embeddings.EmbedContext | None = None
        ) -> list[list[float]]:
            calls.append(texts)
            return [[0.0] * self.dimensions for _ in texts]

    counter = Counting()
    await embeddings.embed_texts(["a", "b"], embedder=counter)
    await embeddings.embed_texts(["a", "b", "c"], embedder=counter)

    assert calls == [["a", "b"], ["c"]], "only what is new reaches the provider"


async def test_a_registered_embedder_replaces_the_default() -> None:
    class Fixed:
        dimensions = embeddings.EMBEDDING_DIMENSIONS

        async def embed(
            self, texts: list[str], *, context: embeddings.EmbedContext | None = None
        ) -> list[list[float]]:
            return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]

    previous = embeddings.current_embedder()
    try:
        embeddings.register_embedder(Fixed())
        [vector] = await embeddings.embed_texts(["anything"])
        assert vector[0] == 1.0
    finally:
        embeddings.register_embedder(previous)
