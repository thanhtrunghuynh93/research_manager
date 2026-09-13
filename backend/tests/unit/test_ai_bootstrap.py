"""Installing the provider at start-up (architecture §10, docs/repo_layout.md §3.1).

The decision this covers: a deployment with no key configured must still run. It gets the
deterministic fake and says so in the log, rather than failing on the first assessment of the week.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.ai import bootstrap
from app.ai.fake import FakeGateway
from app.ai.gateway import OpenAIGateway, current_gateway, register_gateway
from app.core.config import Settings
from app.evidence.index import embeddings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore() -> object:
    """Both registries are process-global; put them back so later tests are unaffected."""
    saved_embedder = embeddings.current_embedder()
    yield
    register_gateway(FakeGateway())
    embeddings.register_embedder(saved_embedder)


def _settings(key: str) -> Settings:
    return Settings(env="test", openai_api_key=SecretStr(key))  # type: ignore[call-arg]


def test_without_a_key_nothing_is_installed_and_the_fake_remains() -> None:
    installed = bootstrap.install(_settings(""))

    assert installed is None
    assert isinstance(current_gateway(), FakeGateway)
    assert isinstance(embeddings.current_embedder(), embeddings.DeterministicEmbedder)


def test_with_a_key_the_provider_gateway_becomes_the_one_in_use() -> None:
    installed = bootstrap.install(_settings("sk-test-not-a-real-key"))

    assert isinstance(installed, OpenAIGateway)
    assert current_gateway() is installed


def test_with_a_key_the_index_embeds_through_the_same_gateway() -> None:
    """One provider seam, not two: repo_layout §3.1 wanted the index to embed through the gateway,
    and §3.3 forbids evidence importing ai — so ai registers the embedder rather than being
    imported (architecture §5.7)."""
    installed = bootstrap.install(_settings("sk-test-not-a-real-key"))

    embedder = embeddings.current_embedder()
    assert not isinstance(embedder, embeddings.DeterministicEmbedder)
    assert getattr(embedder, "gateway", None) is installed
    assert embedder.dimensions == embeddings.EMBEDDING_DIMENSIONS
