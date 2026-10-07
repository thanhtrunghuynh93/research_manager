"""Architecture §10: a project marked `ai_restricted` sends nothing to a model provider.

Indexing is the one place every report entry and every attachment's extracted text passes
through. It used to embed each chunk through the provider, and the restriction had to be enforced
there as well as on the assessment step. Embeddings are gone (ADR 0024): indexing is chunking
alone, and these tests hold it to reaching no provider for any project, restricted or not. The
assessment side is `test_a_restricted_project_is_never_sent_to_a_provider` in
tests/module/assessment/test_pipeline.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway as ai_gateway
from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models, service
from app.evidence.schemas import EvidenceReferenceOut
from app.projects import service as projects_service
from tests.factories import make_project

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
SECRET = "The unpublished protocol, in full, with the participant identifiers."


class _Provider:
    """Stands in for the registered, provider-backed gateway: records anything it is asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        async def _called(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(f"indexing reached the model provider through {name}")

        return _called


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _Provider:
    recorder = _Provider()
    monkeypatch.setattr(ai_gateway, "_gateway", recorder)
    return recorder


async def _project(db: AsyncSession, scope: Scope, *, restricted: bool) -> object:
    project = await make_project(db, scope, title=f"Study {uuid4()}", active=False)
    await projects_service.update_project(
        db, scope, project.id, status="active", ai_restricted=restricted
    )
    return project


async def _index(
    db: AsyncSession, scope: Scope, project: object, text: str
) -> EvidenceReferenceOut:
    return await service.index_evidence(
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

    assert provider.calls == []


async def test_an_unrestricted_project_is_not_sent_either(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    """Nothing about indexing needs a provider, so no project's text goes to one here."""
    project = await _project(db, prof_scope, restricted=False)

    await _index(db, prof_scope, project, "Ordinary work, indexable as usual.")

    assert provider.calls == []


async def test_a_restricted_project_is_still_indexed(
    db: AsyncSession, prof_scope: Scope, provider: _Provider
) -> None:
    """Restricted must mean "local", not "absent": the rows still have to be readable."""
    project = await _project(db, prof_scope, restricted=True)
    reference = await _index(
        db, prof_scope, project, "We reproduced the published baseline within one point."
    )

    hits = await service.chunks_for_reference(db, reference.id)

    assert hits
    assert hits[0].text.startswith("We reproduced the published baseline")
    assert provider.calls == []
