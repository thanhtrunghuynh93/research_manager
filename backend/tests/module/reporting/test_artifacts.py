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

from app.core.errors import ForbiddenError, NotFoundError, ValidationError
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
    version = await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)
    # Confirming no longer reads the file — a job does, seconds later. Running it here is what the
    # worker does, so every test below sees the state the student eventually sees. Re-read rather
    # than reused: `confirm_upload` returned a snapshot taken before the file was read.
    await artifacts.extract_version(db, version.version_id, store=store)
    return (await artifacts.list_versions(db, scope, grant.artifact_id))[-1]


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


# ------------------------------------------------------------------ links (REP-04)


async def test_a_fetched_link_becomes_evidence_like_any_other_attachment(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    async def _fetch(url: str) -> object:
        from app.reporting.links import Fetched

        return Fetched(url=url, content_type="text/markdown", data=NOTE)

    version = await artifacts.attach_link(
        db,
        scope,
        project_id=project.id,
        url="https://arxiv.org/abs/2401.00001",
        supported_claim="the preprint the method comes from",
        store=store,
        fetch=_fetch,
    )

    assert version.extraction_state is ExtractionState.OK
    assert version.uploaded is True
    from app.evidence import service as evidence_service

    assert await evidence_service.search_evidence(
        db, scope, query="difficulty proxy length", project_id=project.id
    )


async def test_a_refused_link_is_recorded_with_the_reason_it_was_not_followed(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """REP-04: the student pointed at something. The record says what, and why we stopped."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    async def _refuse(url: str) -> object:
        from app.reporting.links import LinkRefusedError

        raise LinkRefusedError("localhost resolves to a private or reserved address")

    version = await artifacts.attach_link(
        db,
        scope,
        project_id=project.id,
        url="http://localhost:8000/admin",
        store=store,
        fetch=_refuse,
    )

    assert version.extraction_state is ExtractionState.FAILED
    assert "private or reserved" in version.extraction_note
    assert version.uploaded is False


async def test_a_link_that_is_simply_unreachable_is_recorded_too(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """An unreachable link is a state of the world, not a crash in the submission flow (AC-13)."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    async def _explode(url: str) -> object:
        raise TimeoutError("took too long")

    version = await artifacts.attach_link(
        db, scope, project_id=project.id, url="https://slow.example/x", store=store, fetch=_explode
    )

    assert version.extraction_state is ExtractionState.FAILED
    assert "TimeoutError" in version.extraction_note


async def test_an_attachment_can_be_bound_to_the_entry_it_supports(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    version = await _upload(db, scope, store, project)
    submitted = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Wrote the note attached here.",
                "results": "See the attachment.",
            }
        ],
    )
    entry_id = submitted.entries[0].id

    await artifacts.attach_to_entry(
        db, scope, version.artifact_id, entry_id=entry_id, period_id=period.id
    )

    attached = await artifacts.list_for_entry(db, scope, entry_id=entry_id)
    assert [row.artifact_id for row in attached] == [version.artifact_id]


async def test_only_the_owner_may_move_their_attachment(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    period, project = await _project(db, prof_scope, student_a)
    owner = await identity_service.scope_for(db, student_a)
    version = await _upload(db, owner, store, project)
    outsider = await identity_service.scope_for(db, student_b)

    with pytest.raises((ForbiddenError, Exception)):
        await artifacts.attach_to_entry(
            db, outsider, version.artifact_id, entry_id=project.id, period_id=period.id
        )


# ---------------------------------------------------------------- what the grant is allowed to be
#
# The storage key is built from ids and the checksum, and a presigned PUT is issued for it. The
# ids are ours; the checksum is not, so its *format* is part of the security boundary.


async def test_a_checksum_that_is_not_hex_is_refused(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """64 characters of `../` would normalise the granted key above the workspace prefix."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    traversal = "../" * 21 + "x"
    assert len(traversal) == 64

    with pytest.raises(ValidationError, match="SHA-256"):
        await artifacts.request_upload(
            db,
            scope,
            project_id=project.id,
            filename="notes.md",
            byte_size=len(NOTE),
            sha256=traversal,
            store=store,
        )


async def test_the_key_builder_refuses_a_checksum_it_cannot_trust() -> None:
    """Stated at the boundary as well as at the edge: a key is a path."""
    from uuid import uuid4

    from app.core.storage import storage_key

    with pytest.raises(ValueError, match="hex"):
        storage_key(
            workspace_id=uuid4(),
            artifact_id=uuid4(),
            version_no=1,
            sha256="../" * 21 + "x",
            filename="notes.md",
        )


async def test_an_upload_larger_than_the_limit_is_refused_at_confirm(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """The declared size bounds only the claim; this is the size of what actually arrived."""
    from app.core.config import get_settings

    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    oversized = b"x" * (get_settings().upload_max_file_mb * 1024 * 1024 + 1)
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="notes.md",
        byte_size=8,  # the claim
        sha256=sha256_of(oversized),
        store=store,
    )
    await store.put_bytes(grant.storage_key, oversized, content_type="text/markdown")

    with pytest.raises(ValidationError, match="limit"):
        await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)


async def test_an_artifact_cannot_be_filed_under_another_students_entry(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    """`list_for_entry` shows the professor everything filed here, as that student's evidence."""
    period, project = await _project(db, prof_scope, student_a)
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_b.id, joined_on=date(2026, 9, 1)
    )
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    victim = await identity_service.scope_for(db, student_a)
    submitted = await reporting_service.submit_report(
        db,
        victim,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the ablation.",
                "results": "No improvement.",
            }
        ],
    )
    victim_entry_id = submitted.entries[0].id

    attacker = await identity_service.scope_for(db, student_b)
    mine = await _upload(db, attacker, store, project)

    with pytest.raises(ForbiddenError, match="own author"):
        await artifacts.attach_to_entry(
            db, attacker, mine.artifact_id, entry_id=victim_entry_id, period_id=period.id
        )


async def test_an_artifact_cannot_be_filed_under_an_unrelated_week(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    from uuid import uuid4

    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    submitted = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the ablation.",
                "results": "No improvement.",
            }
        ],
    )
    version = await _upload(db, scope, store, project)

    with pytest.raises(ValidationError, match="different reporting period"):
        await artifacts.attach_to_entry(
            db,
            scope,
            version.artifact_id,
            entry_id=submitted.entries[0].id,
            period_id=uuid4(),
        )


# ------------------------------------------------------------------ listing (REP-04, AC-02)
#
# Without a listing there is no way back to a file: the artifact id appeared only in the response
# to the upload that created it, so a reloaded page lost its own attachments and the professor
# could not reach a student's at all.


async def test_a_student_lists_the_attachments_they_uploaded(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    await _upload(db, scope, store, project, filename="notes.md")
    await _upload(db, scope, store, project, filename="summary.html", data=b"<p>ok</p>")

    rows = await artifacts.list_artifacts(db, scope, project_id=project.id)

    assert {row.filename for row in rows} == {"notes.md", "summary.html"}
    assert all(row.owner_student_id == student_a.id for row in rows)
    assert all(row.uploaded for row in rows)


async def test_the_professor_sees_a_students_attachments(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    await _upload(db, scope, store, project)

    rows = await artifacts.list_artifacts(db, prof_scope, student_id=student_a.id)

    assert [row.filename for row in rows] == ["notes.md"]
    # The filename and what could be read of it, not just an identifier.
    assert rows[0].content_type == "text/markdown"
    assert rows[0].extraction_state is ExtractionState.OK


async def test_one_student_never_sees_anothers_attachments(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    """AC-02: an attachment belongs to the student who attached it, and asking does not tell."""
    _period, project = await _project(db, prof_scope, student_a)
    scope_a = await identity_service.scope_for(db, student_a)
    await _upload(db, scope_a, store, project)
    scope_b = await identity_service.scope_for(db, student_b)

    rows = await artifacts.list_artifacts(db, scope_b, student_id=student_a.id)

    # Empty rather than refused: whether that student has attachments is not B's to learn.
    assert rows == []


async def test_an_upload_that_never_arrived_is_not_listed_as_an_attachment(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """A grant is not a file. Listing one would show the professor evidence that does not exist."""
    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        filename="abandoned.pptx",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )

    rows = await artifacts.list_artifacts(db, prof_scope, student_id=student_a.id)

    assert [row.filename for row in rows] == []


# ------------------------------------------- the attachment survives a provider outage (AC-13)


async def test_a_dead_embedding_provider_does_not_lose_the_attachment(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bytes arrived and the text was extracted before anything indexed it.

    Indexing runs inside the confirming transaction so the chunks commit with the version that
    cites them, which puts the embedding provider on the student's upload path. A provider that is
    down used to surface as a 500 and lose an attachment that was already stored.
    """
    from app.evidence import service as evidence_service

    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    async def _provider_is_down(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("429 insufficient_quota: you have no credits remaining")

    monkeypatch.setattr(evidence_service, "embed_texts", _provider_is_down)

    uploaded = await _upload(db, scope, store, project)

    assert uploaded.extraction_state is ExtractionState.OK
    listed = await artifacts.list_artifacts(db, scope, student_id=student_a.id)
    assert any(one.artifact_id == uploaded.artifact_id for one in listed), (
        "the attachment is on the student's record even though nothing could be indexed"
    )


async def test_the_attachment_is_indexed_when_the_provider_comes_back(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recoverable without the student re-uploading: the extracted text is already in the store."""
    from app.evidence import service as evidence_service

    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    async def _provider_is_down(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(evidence_service, "embed_texts", _provider_is_down)
    uploaded = await _upload(db, scope, store, project)
    monkeypatch.undo()

    # What the retry job does, reading the text back from the object store.
    indexed = await evidence_service.index_artifact_version(db, uploaded.version_id, store=store)

    assert indexed is True
    hits = await evidence_service.search_evidence(db, scope, query="ablation difficulty proxy")
    assert hits, "the attachment is citable once the provider answers again"


async def test_an_attachment_with_no_text_is_a_no_op_for_the_retry(
    db: AsyncSession, prof_scope, student_a: identity_models.User, store: InMemoryObjectStore
) -> None:
    """Nothing to read is not a failure: extraction records three outcomes, not two."""
    from app.evidence import service as evidence_service

    _period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    uploaded = await _upload(db, scope, store, project, filename="figure.png", data=b"\x89PNG\r\n")

    assert (
        await evidence_service.index_artifact_version(db, uploaded.version_id, store=store) is False
    )


# ------------------------------------------------------------------ removal (REP-04, §11)


async def _upload_for_week(
    db: AsyncSession, scope, store: InMemoryObjectStore, project, period
) -> object:
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        period_id=period.id,
        filename="notes.md",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )
    await store.put_bytes(grant.storage_key, NOTE, content_type=grant.content_type)
    version = await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)
    await artifacts.extract_version(db, version.version_id, store=store)
    return version


async def test_removing_a_file_takes_it_out_of_storage_and_out_of_the_index(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    """§11: deletion propagates to file storage, searchable indexes and answer caches."""
    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    version = await _upload_for_week(db, scope, store, project, period)

    indexed = await _evidence_reference_count(db, version.version_id)
    assert indexed == 1, "the attachment is searchable before it is removed"
    assert _stored_keys(store, version.artifact_id), "its bytes are in the store"

    await artifacts.remove_artifact(db, scope, version.artifact_id, store=store)

    assert await _evidence_reference_count(db, version.version_id) == 0
    assert _stored_keys(store, version.artifact_id) == []
    assert await _artifact_exists(db, version.artifact_id) is False


async def test_a_submitted_week_keeps_its_attachments(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    # Before submission the file is part of a draft; afterwards it is part of a record the
    # professor may have read and an assessment may cite, and unpicking that is not the
    # student's to do.
    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    version = await _upload_for_week(db, scope, store, project, period)

    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the ablation",
                "results": "No improvement over the baseline.",
                "deviations": "",
                "next_plan": {"outcomes": ["Try the length control"]},
                "questions": "",
            }
        ],
    )

    with pytest.raises(ValidationError):
        await artifacts.remove_artifact(db, scope, version.artifact_id, store=store)

    assert await _artifact_exists(db, version.artifact_id) is True


async def test_a_co_member_cannot_even_see_the_file_to_remove_it(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    period, project = await _project(db, prof_scope, student_a)
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_b.id, joined_on=date(2026, 9, 1)
    )
    owner = await identity_service.scope_for(db, student_a)
    version = await _upload_for_week(db, owner, store, project, period)

    # Not forbidden — not found. `artifact_visible_to` restricts attachments to the student who
    # attached them, so a co-member on the same project never sees the file at all, and the
    # ownership check inside `remove_artifact` is the second lock rather than the first.
    co_member = await identity_service.scope_for(db, student_b)
    with pytest.raises(NotFoundError):
        await artifacts.remove_artifact(db, co_member, version.artifact_id, store=store)

    assert await _artifact_exists(db, version.artifact_id) is True


def _stored_keys(store: InMemoryObjectStore, artifact_id) -> list[str]:
    """Both keys the attachment owns: the uploaded bytes and the text extracted beside them."""
    return [key for key in store.stored_keys() if str(artifact_id) in key]


async def _evidence_reference_count(db: AsyncSession, version_id) -> int:
    from sqlalchemy import func, select

    from app.evidence.models import EvidenceReference

    return (
        await db.execute(
            select(func.count())
            .select_from(EvidenceReference)
            .where(EvidenceReference.source_id == version_id)
        )
    ).scalar_one()


async def _artifact_exists(db: AsyncSession, artifact_id) -> bool:
    from sqlalchemy import select

    from app.reporting.models import Artifact

    return (
        await db.execute(select(Artifact.id).where(Artifact.id == artifact_id))
    ).scalar_one_or_none() is not None


async def test_confirming_an_upload_does_not_read_the_file(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    """The upload returns as soon as the bytes are safe; a job reads them (REP-04).

    Reading is what made attaching slow — unzipping a deck and embedding what comes out took the
    better part of five seconds on the live stack. None of it is work the student waits through,
    so the version comes back `pending` and nothing is searchable yet.
    """
    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    grant = await artifacts.request_upload(
        db,
        scope,
        project_id=project.id,
        period_id=period.id,
        filename="notes.md",
        byte_size=len(NOTE),
        sha256=sha256_of(NOTE),
        store=store,
    )
    await store.put_bytes(grant.storage_key, NOTE, content_type=grant.content_type)

    version = await artifacts.confirm_upload(db, scope, grant.artifact_id, store=store)

    assert version.uploaded is True, "the bytes are on the record"
    assert version.extraction_state is ExtractionState.PENDING
    assert await _evidence_reference_count(db, version.version_id) == 0

    # What the worker then does, and the state the student ends up seeing.
    await artifacts.extract_version(db, version.version_id, store=store)

    after = (await artifacts.list_versions(db, scope, grant.artifact_id))[-1]
    assert after.extraction_state is ExtractionState.OK
    assert await _evidence_reference_count(db, version.version_id) == 1


async def test_reading_the_same_version_twice_indexes_it_once(
    db: AsyncSession,
    prof_scope,
    student_a: identity_models.User,
    store: InMemoryObjectStore,
) -> None:
    # A redelivered job is the ordinary case for a retried task, not an exceptional one.
    period, project = await _project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    version = await _upload_for_week(db, scope, store, project, period)

    await artifacts.extract_version(db, version.version_id, store=store)

    assert await _evidence_reference_count(db, version.version_id) == 1
