"""Attachments (REP-04, architecture §5.6).

The upload path has one shape worth getting right: the API grants permission to write to a key and
then verifies what actually arrived. A presigned URL is a grant, not a fact, so nothing counts as
attached until the bytes are there and their checksum matches what was promised.

The rest is about honesty afterwards. An unreadable file is marked unread, not indexed as empty,
because the two lead to opposite conclusions about the week.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, ValidationError
from app.core.storage import InMemoryObjectStore, sha256_of
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import artifacts
from app.reporting import service as reporting_service
from app.reporting.models import ExtractionState

pytestmark = pytest.mark.module

NOTE = b"# Week 3\n\nThe ablation did not help; the difficulty proxy was length in disguise."


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


async def _project(
    db: AsyncSession, prof_scope, student: identity_models.User
) -> tuple[object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def _upload(
    db: AsyncSession,
    scope,
    store: InMemoryObjectStore,
    project,
    *,
    filename: str = "notes.md",
    data: bytes = NOTE,
) -> object:
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename=filename,
        byte_size=len(data),
        sha256=sha256_of(data),
        store=store,
    )
    await store.put_bytes(grant.storage_key, data, content_type=grant.content_type)
    return await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)


async def test_a_grant_names_a_key_derived_from_the_checksum(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="notes.md",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )

    assert sha256_of(NOTE) in grant.storage_key
    assert grant.url
    assert grant.expires_in > 0


async def test_nothing_is_attached_until_the_bytes_actually_arrive(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """A presigned URL is a grant, not a fact."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="notes.md",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )

    with pytest.raises(ValidationError, match="not.*uploaded|no object"):
        await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)


async def test_bytes_that_do_not_match_the_promised_checksum_are_refused(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="notes.md",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )
    await store.put_bytes(grant.storage_key, b"something else", content_type="text/markdown")

    with pytest.raises(ValidationError, match="checksum"):
        await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)


async def test_a_file_over_the_configured_limit_is_refused_before_any_grant(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """REP-04: the limit is configurable and enforced before a URL exists, not after a transfer."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ValidationError, match="25 MB|limit"):
        await artifacts.request_upload(
            db,
            scope,
            project_id=project.id,
            filename="huge.pdf",
            byte_size=26 * 1024 * 1024,
            sha256="a" * 64,
            store=store,
        )


async def test_a_confirmed_upload_is_extracted_and_indexed(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    version = await _upload(db, scope, store, project)

    assert version.extraction_state is ExtractionState.OK
    assert version.uploaded is True
    from app.evidence import service as evidence_service

    hits = await evidence_service.search_evidence(
        db, scope, query="difficulty proxy length", project_id=project.id
    )
    assert hits, "an attachment's text is searchable evidence"


async def test_an_unreadable_file_is_marked_unread_rather_than_indexed_as_empty(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """REP-04/ASSESS-06: empty text and unreadable text mean opposite things about the week."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    version = await _upload(
        db, scope, store, project, filename="paper.pdf", data=b"%PDF-1.7 not really"
    )

    assert version.extraction_state is ExtractionState.FAILED
    assert version.extraction_note


async def test_an_image_is_stored_without_being_called_a_failure(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    version = await _upload(
        db, scope, store, project, filename="figure.png", data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    )

    assert version.extraction_state is ExtractionState.UNSUPPORTED


async def test_a_download_needs_the_same_permission_as_reading_the_record(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    """AC-02: a presigned GET is issued only after `visible_to` selects the artifact."""
    _period, project = await _project(db, prof_scope, student_a)
    owner = await identity_service.scope_for(db, student_a)
    version = await _upload(db, owner, store, project)
    outsider = await identity_service.scope_for(db, student_b)

    own = await artifacts.download_url(db, owner, version.artifact_id, store=store)
    assert own.url

    with pytest.raises((ForbiddenError, Exception)):
        await artifacts.download_url(db, outsider, version.artifact_id, store=store)


async def test_the_professor_may_download_any_artifact_in_the_workspace(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    owner = await identity_service.scope_for(db, student_a)
    version = await _upload(db, owner, store, project)

    assert (await artifacts.download_url(db, prof_scope, version.artifact_id, store=store)).url


async def test_a_second_version_keeps_the_first_readable(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """ASSESS-09: an assessment that read version 1 must still be able to open version 1."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    first = await _upload(db, scope, store, project)

    replacement = b"# Week 3 (corrected)\n\nThe proxy was length in disguise."
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="notes.md",
        byte_size=len(replacement),
        sha256=sha256_of(replacement),
        artifact_id=first.artifact_id,
        store=store,
    )
    await store.put_bytes(grant.storage_key, replacement, content_type=grant.content_type)
    second = await artifacts.confirm_upload(db, scope, first.artifact_id, store=store)

    assert second.version_no == first.version_no + 1
    assert await store.get_bytes(first.storage_key) is not None
    versions = await artifacts.list_versions(db, scope, first.artifact_id)
    assert len(versions) == 2


async def test_a_student_cannot_attach_to_a_project_they_are_not_on(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    outsider = await identity_service.scope_for(db, student_b)

    with pytest.raises(ForbiddenError):
        await artifacts.request_upload(
            db,
            outsider,
            project_id=project.id,
            filename="notes.md",
            byte_size=len(NOTE),
            sha256=sha256_of(NOTE),
            store=store,
        )
