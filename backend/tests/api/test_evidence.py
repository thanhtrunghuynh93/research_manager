"""The evidence routes: search over the index and the other end of a citation (QA-02, QA-03)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.identity import models as identity_models
from tests.factories import login

pytestmark = pytest.mark.api


async def test_evidence_search_is_reachable_and_scoped(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """QA-02/AUTH-02: the same predicate as everywhere else, through an ordinary endpoint."""
    await login(client, student_a)

    response = await client.get("/api/v1/evidence/search?q=baseline")

    assert response.status_code == 200
    assert response.json() == []
