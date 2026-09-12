"""Architecture §10: a project marked `ai_restricted` sends nothing to a model provider.

The restriction was enforced on the completion step only. Indexing is the other, larger door: it
is the one place every report entry, every artifact's extracted text, and every repository diff
passes through, and it ran through the registered — that is, provider-backed — embedder for every
project alike.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models, service
from app.evidence.index import embeddings
from app.projects import service as projects_service

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
SECRET = "The unpublished protocol, in full, with the participant identifiers."


class _Provider:
    """Stands in for the registered, provider-backed embedder: records what it was asked to send."""

    dimensions = embeddings.EMBEDDING_DIMENSIONS

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def embed(
        self, texts: list[str], *, context: embeddings.EmbedContext | None = None
    ) -> list[list[float]]:
        self.sent.extend(texts)
        return [[0.0] * self.dimensions for _ in texts]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _Provider:
    recorder = _Provider()
    monkeypatch.setattr(embeddings, "_embedder", recorder)
    embeddings.clear_cache()
    return recorder


async def _project(db: AsyncSession, scope: Scope, *, restricted: bool) -> object:
    project = await projects_service.create_project(
        db, scope, title=f"Study {uuid4()}", stage="implementation"
    )
    await projects_service.update_project(
        db, scope, project.id, status="active", ai_restricted=restricted
    )
    return project


async def _index(db: AsyncSession, scope: Scope, project: object, text: str) -> None:
    await service.index_evidence(
        db,
        workspace_id=scope.workspace_id,
        project_id=project.id,
        source_kind=models.EvidenceSourceKind.REPORT_ENTRY,
        source_id=uuid4(),
        source_version="1",
        locator="report entry",
        text=text,
        visibility=Visibility.PROJECT_SHARED,
        source_time=WEEK,
    )


async def test_a_restricted_project_is_not_sent_to_the_provider(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    project = await _project(db, prof_scope, restricted=True)

    await _index(db, prof_scope, project, SECRET)

    assert provider.sent == []


async def test_an_unrestricted_project_still_is(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    """The restriction is a per-project decision, not a way of switching the provider off."""
    project = await _project(db, prof_scope, restricted=False)

    await _index(db, prof_scope, project, "Ordinary work, indexable as usual.")

    assert provider.sent


async def test_a_restricted_project_is_still_searchable(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    """Restricted must mean "local", not "absent": the rows still have to be retrievable."""
    project = await _project(db, prof_scope, restricted=True)
    await _index(db, prof_scope, project, "We reproduced the published baseline within one point.")

    hits = await service.search_evidence(
        db, prof_scope, query="baseline", project_id=project.id, mode="lexical"
    )

    assert hits
    assert provider.sent == []


async def test_a_query_against_a_restricted_project_is_not_sent_either(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    """The question is research text too, and it names what the professor is looking for."""
    project = await _project(db, prof_scope, restricted=True)
    await _index(db, prof_scope, project, "Ablation notes.")

    await service.search_evidence(
        db, prof_scope, query="unpublished protocol", project_id=project.id, mode="hybrid"
    )

    assert provider.sent == []
