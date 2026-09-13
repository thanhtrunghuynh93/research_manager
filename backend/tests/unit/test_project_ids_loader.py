"""The seam through which projects supplies a student's memberships to their Scope.

identity resolves the session but sits below projects in the layer order, so the loader is
registered rather than imported (architecture §6.1).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import authz


@pytest.fixture(autouse=True)
def _restore_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authz, "_project_ids_loader", None)


@pytest.mark.unit
async def test_no_registered_loader_means_no_project_access() -> None:
    loaded = await authz.load_project_ids(None, uuid4(), uuid4())  # type: ignore[arg-type]

    assert loaded == frozenset(), "fail closed: no memberships until projects says otherwise"


@pytest.mark.unit
async def test_a_registered_loader_supplies_the_memberships() -> None:
    project_id = uuid4()

    @authz.register_project_ids_loader
    async def _loader(session: AsyncSession, workspace_id: object, user_id: object) -> frozenset:
        return frozenset({project_id})

    loaded = await authz.load_project_ids(None, uuid4(), uuid4())  # type: ignore[arg-type]

    assert loaded == frozenset({project_id})
