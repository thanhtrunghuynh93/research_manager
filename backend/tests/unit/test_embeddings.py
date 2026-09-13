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


# ---------------------------------------------------------------- the cache under pressure
#
# The eviction used to empty the whole cache, and it ran inside the fill loop — so it discarded
# vectors the current call had just written and was about to read back. A long-running worker
# crossed the limit after roughly ten thousand chunks and then raised KeyError on every call,
# killing indexing and search alike. Nothing exercised it because the tests clear the cache first.


async def test_a_full_cache_does_not_break_the_call_that_fills_it() -> None:
    from app.evidence.index import embeddings

    embeddings.clear_cache()
    embedder = embeddings.DeterministicEmbedder()
    model = type(embedder).__name__
    for index in range(embeddings.CACHE_LIMIT):
        embeddings._cache[(model, embeddings._key(f"filler-{index}"))] = [0.0]

    vectors = await embeddings.embed_texts(["new-a", "new-b", "new-c"], embedder=embedder)

    assert len(vectors) == 3
    assert all(len(vector) == embedder.dimensions for vector in vectors)


async def test_the_cache_stays_within_its_limit() -> None:
    from app.evidence.index import embeddings

    embeddings.clear_cache()
    embedder = embeddings.DeterministicEmbedder()
    await embeddings.embed_texts(
        [f"chunk-{index}" for index in range(embeddings.CACHE_LIMIT + 50)], embedder=embedder
    )

    assert len(embeddings._cache) == embeddings.CACHE_LIMIT


async def test_a_batch_larger_than_the_cache_still_returns_every_vector() -> None:
    from app.evidence.index import embeddings

    embeddings.clear_cache()
    embedder = embeddings.DeterministicEmbedder()

    texts = [f"chunk-{index}" for index in range(embeddings.CACHE_LIMIT + 10)]
    vectors = await embeddings.embed_texts(texts, embedder=embedder)

    assert len(vectors) == len(texts)


async def test_the_gateways_vector_cache_evicts_one_entry_rather_than_all() -> None:
    """The same shape in `app.ai.gateway`, reached by the provider-backed embedder."""
    from app.ai import gateway

    gateway.clear_embedding_cache()
    for index in range(gateway._VECTOR_CACHE_LIMIT + 5):
        gateway._remember(f"m:{index}", [float(index)])

    assert len(gateway._VECTORS) == gateway._VECTOR_CACHE_LIMIT
    assert "m:0" not in gateway._VECTORS, "the oldest went"
    assert gateway._VECTORS[f"m:{gateway._VECTOR_CACHE_LIMIT + 4}"] == [
        float(gateway._VECTOR_CACHE_LIMIT + 4)
    ], "the newest stayed"
