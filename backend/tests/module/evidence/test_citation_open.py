"""QA-03: a citation has to open something, under the same permissions it was built under.

`get_reference` is the other end of every citation link the assistant and the review screen
render. It shipped unable to run at all: `visible_to` fails closed, and no visibility policy was
registered for `EvidenceReference`, so every call raised `RuntimeError` before touching the
database. Nothing in the suite called it, which is why that was invisible.

The access rules restated here are the ones `index.retrieval.visible_chunks` applies to the
chunks beneath each reference; opening a citation must not be a way around them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import NotFoundError
from app.core.types import Visibility
from app.evidence import models, service
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def _project(db: AsyncSession, scope: Scope, title: str = "Baseline") -> object:
    project = await projects_service.create_project(db, scope, title=title, stage="implementation")
    await projects_service.update_project(db, scope, project.id, status="active")
    return project


async def _reference(
    db: AsyncSession,
    scope: Scope,
    project: object,
    *,
    visibility: Visibility = Visibility.PROJECT_SHARED,
    owner_student_id: object = None,
) -> object:
    return await service.index_evidence(
        db,
        workspace_id=scope.workspace_id,
        project_id=project.id,
        source_kind=models.EvidenceSourceKind.REPORT_ENTRY,
        source_id=uuid4(),
        source_version="1",
        locator="report entry",
        text="We reproduced the published baseline within one point.",
        visibility=visibility,
        owner_student_id=owner_student_id,
        source_time=WEEK,
    )


async def test_a_professor_opens_a_citation(db: AsyncSession, prof_scope: Scope) -> None:
    project = await _project(db, prof_scope)
    reference = await _reference(db, prof_scope, project)

    opened = await service.get_reference(db, prof_scope, reference.id)

    assert opened.id == reference.id
    assert opened.locator == "report entry"


async def test_a_student_opens_a_citation_shared_with_their_project(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    project = await _project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    reference = await _reference(db, prof_scope, project)

    scope = await identity_service.scope_for(db, student_a)
    opened = await service.get_reference(db, scope, reference.id)

    assert opened.id == reference.id


async def test_a_student_cannot_open_a_citation_for_a_project_they_are_not_on(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    project = await _project(db, prof_scope)
    reference = await _reference(db, prof_scope, project)

    scope = await identity_service.scope_for(db, student_a)
    with pytest.raises(NotFoundError):
        await service.get_reference(db, scope, reference.id)


async def test_a_student_cannot_open_a_professor_only_citation(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    """QA-06: the professor's own notes are not reachable by opening a link to them."""
    project = await _project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    reference = await _reference(db, prof_scope, project, visibility=Visibility.PROFESSOR_ONLY)

    scope = await identity_service.scope_for(db, student_a)
    with pytest.raises(NotFoundError):
        await service.get_reference(db, scope, reference.id)


async def test_a_student_cannot_open_another_students_private_citation(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    project = await _project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_b.id)
    reference = await _reference(
        db,
        prof_scope,
        project,
        visibility=Visibility.STUDENT_PRIVATE,
        owner_student_id=student_b.id,
    )

    own = await identity_service.scope_for(db, student_b)
    assert (await service.get_reference(db, own, reference.id)).id == reference.id

    other = await identity_service.scope_for(db, student_a)
    with pytest.raises(NotFoundError):
        await service.get_reference(db, other, reference.id)
