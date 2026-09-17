"""Attachments: uploads, links, extraction, and download (REP-04, architecture §5.6).

The upload has a deliberate shape. The API validates the size and issues a presigned PUT, the
browser sends the bytes straight to object storage, and then we *verify what arrived*. A presigned
URL is a grant, not a fact: nothing is attached until the object exists and its checksum matches
what was promised. That ordering is what keeps a 25 MB transfer off the application process while
still leaving the application the authority over what counts as evidence.

Versions are kept. Replacing a figure creates version 2 and leaves version 1 readable, because an
assessment that cited version 1 has to be able to open version 1 (ASSESS-09).

Extraction records three outcomes rather than two — read, unreadable, nothing-to-read — because a
file we could not parse and a file with no text lead to opposite conclusions about the week.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope, visible_to
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.ids import uuid7
from app.core.jobs import defer_after_commit
from app.core.storage import (
    ObjectStore,
    content_type_for,
    current_store,
    extension_for_content_type,
    extracted_text_key,
    is_sha256_hex,
    sha256_of,
    storage_key,
)
from app.identity import service as identity_service
from app.reporting import events, extraction, links
from app.reporting.models import (
    Artifact,
    ArtifactKind,
    ArtifactVersion,
    ExtractionState,
    ProjectReportEntry,
    ReportVersion,
    WeeklyReport,
)

log = logging.getLogger(__name__)

# REP-04 proposes 25 MB per file and a configurable total per project entry.
MAX_ENTRY_TOTAL_MB = 200


@dataclass(frozen=True, slots=True)
class UploadGrant:
    """Permission to write one object, and where to write it."""

    artifact_id: UUID
    version_no: int
    storage_key: str
    content_type: str
    url: str
    expires_in: int
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ArtifactOut:
    """One attachment as a reader meets it: what it is, who attached it, and what we could read.

    The current version's details are folded in, because a list of attachments with no filename
    and no extraction state is a list of identifiers.
    """

    artifact_id: UUID
    owner_student_id: UUID
    project_id: UUID | None
    period_id: UUID | None
    entry_id: UUID | None
    kind: ArtifactKind
    filename: str
    supported_claim: str
    source_url: str | None
    version_no: int
    byte_size: int
    content_type: str
    extraction_state: ExtractionState
    extraction_note: str
    uploaded: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactVersionOut:
    artifact_id: UUID
    version_id: UUID
    version_no: int
    filename: str
    sha256: str | None
    byte_size: int
    content_type: str
    storage_key: str
    extraction_state: ExtractionState
    extraction_note: str
    truncated: bool
    uploaded: bool
    created_at: datetime


def max_file_bytes() -> int:
    return get_settings().upload_max_file_mb * 1024 * 1024


# ------------------------------------------------------------------ upload


async def request_upload(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID,
    filename: str,
    byte_size: int,
    sha256: str,
    supported_claim: str = "",
    entry_id: UUID | None = None,
    period_id: UUID | None = None,
    artifact_id: UUID | None = None,
    store: ObjectStore | None = None,
) -> UploadGrant:
    """Validate, then grant permission to write exactly one key.

    The size is checked here rather than after the transfer, because refusing a 40 MB file once it
    has already crossed the network is a worse experience and a worse use of the host.
    """
    scope.require_project(project_id)
    if byte_size <= 0:
        raise ValidationError("an empty file is not evidence")
    if byte_size > max_file_bytes():
        limit = get_settings().upload_max_file_mb
        raise ValidationError(f"this file is larger than the {limit} MB per-file limit")
    if not is_sha256_hex(sha256):
        # Checked as a *format*, not only a length: the checksum is interpolated into the object
        # key, and a 64-character path fragment would grant a write outside the workspace prefix.
        raise ValidationError("a SHA-256 checksum of the file is required before uploading")

    artifact = await _open_artifact(
        session,
        scope,
        artifact_id=artifact_id,
        project_id=project_id,
        filename=filename,
        supported_claim=supported_claim,
        entry_id=entry_id,
        period_id=period_id,
    )
    version_no = artifact.current_version_no + 1
    key = storage_key(
        workspace_id=scope.workspace_id,
        artifact_id=artifact.id,
        version_no=version_no,
        sha256=sha256,
        filename=filename,
    )
    content_type = content_type_for(filename)

    # `current_version_no` only advances on confirm, so a second grant before one computes the
    # same version_no and violates uq (artifact_id, version_no). Asking again is ordinary — the
    # presigned URL expires in fifteen minutes, and a student who picked the wrong file asks for
    # another — and the old behaviour made every retry a 500 and the artifact permanently
    # unreplaceable. The pending row is re-pointed instead: nothing was uploaded against it.
    pending = await _pending_version(session, artifact.id)
    if pending is not None and pending.version_no == version_no:
        if pending.storage_key != key:
            await (store or current_store()).delete(pending.storage_key)
        pending.sha256 = sha256
        pending.byte_size = byte_size
        pending.content_type = content_type
        pending.storage_key = key
        pending.extraction_state = ExtractionState.PENDING
    else:
        session.add(
            ArtifactVersion(
                workspace_id=scope.workspace_id,
                artifact_id=artifact.id,
                version_no=version_no,
                sha256=sha256,
                byte_size=byte_size,
                content_type=content_type,
                storage_key=key,
                extraction_state=ExtractionState.PENDING,
            )
        )
    await session.flush()

    active = store or current_store()
    presigned = await active.presigned_put(key, content_type=content_type)
    return UploadGrant(
        artifact_id=artifact.id,
        version_no=version_no,
        storage_key=key,
        content_type=content_type,
        url=presigned.url,
        expires_in=presigned.expires_in,
        headers=presigned.headers,
    )


async def confirm_upload(
    session: AsyncSession,
    scope: Scope,
    artifact_id: UUID,
    *,
    store: ObjectStore | None = None,
) -> ArtifactVersionOut:
    """Verify what arrived, then extract and index it.

    This is where a grant becomes a fact. The checksum is re-computed from the stored object rather
    than trusted from the request, because the request is the thing being checked.
    """
    artifact = await _require_artifact(session, scope, artifact_id)
    version = await _pending_version(session, artifact_id)
    if version is None:
        raise ValidationError("there is no pending upload for this artifact")

    active = store or current_store()

    # The declared size bounded only what the client *said* it would send; this is what arrived.
    # Checked from the object's metadata rather than after reading it, so an oversized upload
    # never crosses into this process (the point of granting a direct PUT in the first place).
    info = await active.head(version.storage_key)
    if info is None:
        raise ValidationError("no object was uploaded to the granted location")
    if info.byte_size > max_file_bytes():
        limit = get_settings().upload_max_file_mb
        await active.delete(version.storage_key)
        raise ValidationError(f"this file is larger than the {limit} MB per-file limit")

    data = await active.get_bytes(version.storage_key)
    if data is None:
        raise ValidationError("no object was uploaded to the granted location")
    if version.sha256 and sha256_of(data) != version.sha256:
        # Refuse rather than accept-and-correct: the checksum is the student's statement of what
        # they meant to attach, and a mismatch means we do not know which file this is.
        raise ValidationError("the uploaded file's checksum does not match the one declared")

    version.byte_size = len(data)
    version.uploaded = True
    # Reading the file is the slow part — a PPTX to unzip and walk, then an embedding round trip,
    # which together took the better part of five seconds on the live stack. It is not work the
    # student needs to wait through: the bytes are safe, the checksum matched, and the attachment
    # is on the record. So the version stays `pending` and a job picks it up, which is why the
    # badge beside it reads "Reading…" until it does.
    version.extraction_state = ExtractionState.PENDING

    artifact.current_version_no = version.version_no
    write_audit(
        session,
        scope=scope,
        action="artifact.uploaded",
        target_table="artifact_versions",
        target_id=version.id,
        after={
            "filename": artifact.filename,
            "version_no": version.version_no,
            "extraction_state": version.extraction_state.value,
        },
    )
    await session.flush()
    _defer_extraction(session, version.id)
    return _out(artifact, version)


# ------------------------------------------------------------------ links (REP-04)


async def attach_link(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID,
    url: str,
    supported_claim: str = "",
    entry_id: UUID | None = None,
    period_id: UUID | None = None,
    store: ObjectStore | None = None,
    fetch: Any = None,
) -> ArtifactVersionOut:
    """Record a linked artifact, fetching a snapshot when the link is safe to fetch.

    A refused link is still recorded: the student pointed at something, and the record should say
    what they pointed at and why we did not follow it (REPO-08).
    """
    scope.require_project(project_id)
    artifact = Artifact(
        workspace_id=scope.workspace_id,
        owner_student_id=scope.user_id,
        project_id=project_id,
        entry_id=entry_id,
        period_id=period_id,
        kind=ArtifactKind.LINK,
        filename=url.rsplit("/", 1)[-1] or "link",
        supported_claim=supported_claim,
        source_url=url,
    )
    session.add(artifact)
    await session.flush()

    key = storage_key(
        workspace_id=scope.workspace_id,
        artifact_id=artifact.id,
        version_no=1,
        sha256="0" * 64,
        filename=artifact.filename,
    )
    version = ArtifactVersion(
        workspace_id=scope.workspace_id,
        artifact_id=artifact.id,
        version_no=1,
        storage_key=key,
        content_type="text/plain",
    )
    session.add(version)

    try:
        fetched = await (fetch or links.fetch)(url)
    except links.LinkRefusedError as refusal:
        version.extraction_state = ExtractionState.FAILED
        version.extraction_note = str(refusal)
        artifact.current_version_no = 1
        await session.flush()
        return _out(artifact, version)
    except Exception as error:  # noqa: BLE001 - an unreachable link is a state, not a crash
        version.extraction_state = ExtractionState.FAILED
        version.extraction_note = f"the link could not be fetched ({type(error).__name__})"
        artifact.current_version_no = 1
        await session.flush()
        return _out(artifact, version)

    active = store or current_store()
    await active.put_bytes(key, fetched.data, content_type=fetched.content_type)
    version.sha256 = sha256_of(fetched.data)
    version.byte_size = len(fetched.data)
    version.content_type = fetched.content_type
    version.uploaded = True

    # The server's Content-Type, not the URL's last path segment: `/abs/2401.00001` has no
    # extension worth reading, and the response says what it actually sent.
    extension = extension_for_content_type(fetched.content_type)
    result = extraction.extract(
        f"{artifact.filename}.{extension}" if extension else artifact.filename, fetched.data
    )
    version.extraction_state = ExtractionState(result.state.value)
    version.extraction_note = result.note
    version.truncated = result.truncated or fetched.truncated
    if result.text:
        text_key = extracted_text_key(key)
        await active.put_bytes(text_key, result.text.encode("utf-8"), content_type="text/plain")
        version.extracted_text_key = text_key

    artifact.current_version_no = 1
    await session.flush()
    await _index(session, artifact, version, result.text)
    return _out(artifact, version)


# ------------------------------------------------------------------ reads


async def download_url(
    session: AsyncSession,
    scope: Scope,
    artifact_id: UUID,
    *,
    version_no: int | None = None,
    store: ObjectStore | None = None,
) -> Any:
    """AC-02: a presigned GET is issued only after the predicate selects the artifact."""
    artifact = await _require_artifact(session, scope, artifact_id)
    version = await _version(session, artifact_id, version_no or artifact.current_version_no)
    if version is None or not version.uploaded:
        raise NotFoundError("this artifact has no stored version")

    active = store or current_store()
    return await active.presigned_get(version.storage_key, filename=artifact.filename)


async def list_artifacts(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> list[ArtifactOut]:
    """The attachments the caller may see, newest first (REP-04, AC-02).

    The predicate does the whole job: a professor sees the workspace, a student sees only what
    they attached. `student_id` therefore narrows a professor's view and can only ever narrow a
    student's — asking for someone else's returns nothing rather than refusing, because whether
    that student exists is not something the asker is entitled to learn.
    """
    # `current_version_no` only advances on confirm, so zero means a grant was issued and the
    # bytes never arrived — a file the student abandoned or whose upload failed. It has no
    # content, its download 404s, and showing it to the professor as an attachment is a lie. A
    # link that was refused kept version 1 and its reason, and is deliberately still here.
    query = select(Artifact).where(visible_to(scope, Artifact), Artifact.current_version_no > 0)
    if student_id is not None:
        query = query.where(Artifact.owner_student_id == student_id)
    if project_id is not None:
        query = query.where(Artifact.project_id == project_id)
    if period_id is not None:
        query = query.where(Artifact.period_id == period_id)
    rows = (await session.execute(query.order_by(Artifact.created_at.desc()))).scalars().all()

    out: list[ArtifactOut] = []
    for artifact in rows:
        version = await _version(session, artifact.id, artifact.current_version_no)
        out.append(
            ArtifactOut(
                artifact_id=artifact.id,
                owner_student_id=artifact.owner_student_id,
                project_id=artifact.project_id,
                period_id=artifact.period_id,
                entry_id=artifact.entry_id,
                kind=artifact.kind,
                filename=artifact.filename,
                supported_claim=artifact.supported_claim,
                source_url=artifact.source_url,
                version_no=artifact.current_version_no,
                byte_size=version.byte_size if version else 0,
                content_type=version.content_type if version else "",
                extraction_state=(version.extraction_state if version else ExtractionState.PENDING),
                extraction_note=version.extraction_note if version else "",
                uploaded=bool(version and version.uploaded),
                created_at=artifact.created_at,
            )
        )
    return out


async def list_versions(
    session: AsyncSession, scope: Scope, artifact_id: UUID
) -> list[ArtifactVersionOut]:
    artifact = await _require_artifact(session, scope, artifact_id)
    rows = (
        (
            await session.execute(
                select(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == artifact_id)
                .order_by(ArtifactVersion.version_no)
            )
        )
        .scalars()
        .all()
    )
    return [_out(artifact, row) for row in rows]


async def list_for_entry(
    session: AsyncSession, scope: Scope, *, entry_id: UUID
) -> list[ArtifactVersionOut]:
    artifacts = (
        (
            await session.execute(
                select(Artifact)
                .where(Artifact.entry_id == entry_id, visible_to(scope, Artifact))
                .order_by(Artifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for artifact in artifacts:
        version = await _version(session, artifact.id, artifact.current_version_no)
        if version is not None:
            out.append(_out(artifact, version))
    return out


async def attach_to_entry(
    session: AsyncSession, scope: Scope, artifact_id: UUID, *, entry_id: UUID, period_id: UUID
) -> None:
    """Bind a draft's file to the entry it supports, once the entry exists.

    `entry_id` and `period_id` are checked, not stored as given. `Artifact.entry_id` carries no
    foreign key, and `list_for_entry` shows the professor everything filed under an entry — so an
    unchecked value here would let one student's file appear as evidence supporting another
    student's entry, or be filed under a week it has nothing to do with.
    """
    artifact = await _require_artifact(session, scope, artifact_id)
    if artifact.owner_student_id != scope.user_id and not scope.is_prof:
        raise ForbiddenError("only the student who attached this artifact may move it")

    owner_id, entry_period_id = await _entry_owner_and_period(session, scope, entry_id)
    if owner_id != artifact.owner_student_id:
        raise ForbiddenError("an artifact can only support its own author's entry")
    if entry_period_id != period_id:
        raise ValidationError("that entry belongs to a different reporting period")

    artifact.entry_id = entry_id
    artifact.period_id = period_id
    await session.flush()


async def _entry_owner_and_period(
    session: AsyncSession, scope: Scope, entry_id: UUID
) -> tuple[UUID, UUID]:
    """Whose entry this is and which week it is for, within the caller's workspace."""
    row = (
        await session.execute(
            select(WeeklyReport.student_id, WeeklyReport.period_id)
            .join(ReportVersion, ReportVersion.report_id == WeeklyReport.id)
            .join(ProjectReportEntry, ProjectReportEntry.report_version_id == ReportVersion.id)
            .where(
                ProjectReportEntry.id == entry_id,
                ProjectReportEntry.workspace_id == scope.workspace_id,
            )
        )
    ).first()
    if row is None:
        raise NotFoundError("report entry not found")
    return row[0], row[1]


# ------------------------------------------------------------------ internals


async def _open_artifact(
    session: AsyncSession,
    scope: Scope,
    *,
    artifact_id: UUID | None,
    project_id: UUID,
    filename: str,
    supported_claim: str,
    entry_id: UUID | None,
    period_id: UUID | None,
) -> Artifact:
    if artifact_id is not None:
        artifact = await _require_artifact(session, scope, artifact_id)
        if artifact.owner_student_id != scope.user_id and not scope.is_prof:
            raise ForbiddenError("only the student who attached this artifact may replace it")
        return artifact

    artifact = Artifact(
        id=uuid7(),
        workspace_id=scope.workspace_id,
        owner_student_id=scope.user_id,
        project_id=project_id,
        entry_id=entry_id,
        period_id=period_id,
        kind=ArtifactKind.UPLOAD,
        filename=filename,
        supported_claim=supported_claim,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def _defer_extraction(session: AsyncSession, version_id: UUID) -> None:
    """Hand the reading to a job, once this transaction commits. Keyed on the version.

    Imported inside the function because `reporting.tasks` imports this module back. Swallowed on
    failure like the other defers — the attachment is stored and on the record, and a job that was
    never queued is a file that reads late rather than an upload that was lost.
    """
    from app.reporting import tasks

    try:
        defer_after_commit(
            session,
            tasks.extract_artifact,
            queueing_lock=f"extract-artifact:{version_id}",
            version_id=str(version_id),
        )
    except Exception:  # noqa: BLE001 - the stored attachment is what must survive
        log.exception("could not queue the text extraction of artifact version %s", version_id)


async def extract_version(
    session: AsyncSession,
    version_id: UUID,
    *,
    store: ObjectStore | None = None,
) -> ExtractionState:
    """Read the text out of a stored file and hand it to evidence (REP-04).

    Split out of `confirm_upload` so it can run in a worker: the student's upload returns as soon
    as the bytes are safe, and this follows within seconds. Unscoped, like the other job entry
    points, because a worker has no request to borrow a Scope from — the version id came from the
    job that the upload itself enqueued.

    Idempotent. A redelivered job re-reads the same bytes and re-indexes the same version, and
    `index_evidence` replaces a reference's chunks rather than adding a second copy.
    """
    version = (
        await session.execute(select(ArtifactVersion).where(ArtifactVersion.id == version_id))
    ).scalar_one_or_none()
    if version is None:
        return ExtractionState.FAILED  # Removed before the job ran; nothing to read.
    artifact = (
        await session.execute(select(Artifact).where(Artifact.id == version.artifact_id))
    ).scalar_one_or_none()
    if artifact is None:
        return ExtractionState.FAILED

    active = store or current_store()
    data = await active.get_bytes(version.storage_key)
    if data is None:
        version.extraction_state = ExtractionState.FAILED
        version.extraction_note = "the stored object could not be read back"
        await session.flush()
        return version.extraction_state

    result = extraction.extract(artifact.filename, data)
    version.extraction_state = ExtractionState(result.state.value)
    version.extraction_note = result.note
    version.truncated = result.truncated
    if result.text:
        text_key = extracted_text_key(version.storage_key)
        await active.put_bytes(text_key, result.text.encode("utf-8"), content_type="text/plain")
        version.extracted_text_key = text_key
    await session.flush()
    await _index(session, artifact, version, result.text)
    return version.extraction_state


async def remove_artifact(
    session: AsyncSession,
    scope: Scope,
    artifact_id: UUID,
    *,
    store: ObjectStore | None = None,
) -> None:
    """REP-04: the student takes back a file they attached, while the week is still theirs.

    Bounded by submission rather than by time. Before the week is submitted the attachment is part
    of a draft and removing it is correcting a mistake; afterwards it is part of a record the
    professor may have read and an assessment may cite, and unpicking that is not a student's to
    do. The refusal says which it is, because "you cannot remove this" without the reason reads as
    a bug.

    A real deletion, not a hidden row (requirements §11): the stored object, the extracted text
    beside it, the evidence references indexed from every version, and the cached answers that
    could still quote it. All of it inside one transaction, so a failure anywhere leaves the
    attachment whole rather than half-gone.
    """
    artifact = await _require_artifact(session, scope, artifact_id)
    if artifact.owner_student_id != scope.user_id:
        raise ForbiddenError("only the student who attached this file may remove it")
    if await _week_is_submitted(session, artifact):
        raise ValidationError(
            "this week has been submitted, so its attachments are part of the record; "
            "ask your professor to remove it"
        )

    versions = list(
        (
            await session.execute(
                select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
            )
        )
        .scalars()
        .all()
    )

    # Evidence first, and it is allowed to fail the whole removal: a reference left behind is a
    # file the assistant can still quote after the student took it back.
    await events.emit(
        events.ArtifactRemoved(
            workspace_id=artifact.workspace_id,
            artifact_id=artifact.id,
            version_ids=tuple(version.id for version in versions),
        ),
        session,
    )

    active = store or current_store()
    for version in versions:
        for key in (version.storage_key, version.extracted_text_key):
            if key:
                await active.delete(key)

    write_audit(
        session,
        scope=scope,
        action="artifact.removed",
        target_table="artifacts",
        target_id=artifact.id,
        before={"filename": artifact.filename, "versions": len(versions)},
    )
    # Only the artifact: `artifact_versions` carries an ON DELETE CASCADE onto it, so deleting
    # the versions here as well asks the database to remove rows it has already removed.
    await session.delete(artifact)
    # AUTH-03: an answer cached while the file was readable must not outlive it.
    await identity_service.advance_access_epoch(session, artifact.workspace_id)
    await session.flush()


async def _week_is_submitted(session: AsyncSession, artifact: Artifact) -> bool:
    """Has the owner already submitted the week this attachment belongs to?

    A file attached outside any period — which the upload form does not produce, but the API
    allows — has no week to be part of, so there is nothing to protect.
    """
    if artifact.period_id is None:
        return False
    submitted = (
        await session.execute(
            select(WeeklyReport.current_version_id).where(
                WeeklyReport.student_id == artifact.owner_student_id,
                WeeklyReport.period_id == artifact.period_id,
            )
        )
    ).scalar_one_or_none()
    return submitted is not None


async def _require_artifact(session: AsyncSession, scope: Scope, artifact_id: UUID) -> Artifact:
    artifact = (
        await session.execute(
            select(Artifact).where(Artifact.id == artifact_id, visible_to(scope, Artifact))
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("artifact not found")
    return artifact


async def _version(
    session: AsyncSession, artifact_id: UUID, version_no: int
) -> ArtifactVersion | None:
    return (
        await session.execute(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.version_no == version_no,
            )
        )
    ).scalar_one_or_none()


async def _pending_version(session: AsyncSession, artifact_id: UUID) -> ArtifactVersion | None:
    return (
        await session.execute(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.uploaded.is_(False),
            )
            .order_by(ArtifactVersion.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _index(
    session: AsyncSession, artifact: Artifact, version: ArtifactVersion, text: str
) -> None:
    """Announce that an attachment is now readable. Evidence decides what to do with that.

    Reporting does not import evidence: the layer runs the other way, and this is the same seam a
    submitted report goes through (architecture §4.1). The event is emitted inside the caller's
    transaction, so the file and the chunks that cite it commit together — waiting for a job would
    leave the week's assessment reading a snapshot missing the file uploaded to support it.
    """
    if not text.strip():
        return
    await events.emit(
        events.ArtifactExtracted(
            workspace_id=artifact.workspace_id,
            artifact_id=artifact.id,
            version_id=version.id,
            version_no=version.version_no,
            project_id=artifact.project_id,
            owner_student_id=artifact.owner_student_id,
            supported_claim=artifact.supported_claim,
            text=text,
            source_time=version.created_at,
        ),
        session,
    )


def _out(artifact: Artifact, version: ArtifactVersion) -> ArtifactVersionOut:
    return ArtifactVersionOut(
        artifact_id=artifact.id,
        version_id=version.id,
        version_no=version.version_no,
        filename=artifact.filename,
        sha256=version.sha256,
        byte_size=version.byte_size,
        content_type=version.content_type,
        storage_key=version.storage_key,
        extraction_state=version.extraction_state,
        extraction_note=version.extraction_note,
        truncated=version.truncated,
        uploaded=version.uploaded,
        created_at=version.created_at,
    )


# ------------------------------------------------------------------ job-level reads


@dataclass(frozen=True, slots=True)
class ArtifactForIndexing:
    """Everything the evidence index needs about one attachment version.

    A job-level read: no Scope to hand, and the event that first carried these fields is long gone
    by the time a retry runs. Reading them back means the retry cannot index under a workspace or
    an owner that a stale job argument claimed.
    """

    workspace_id: UUID
    artifact_id: UUID
    version_id: UUID
    version_no: int
    project_id: UUID | None
    owner_student_id: UUID
    supported_claim: str
    text: str
    source_time: datetime


async def version_for_indexing(
    session: AsyncSession, version_id: UUID, *, store: ObjectStore | None = None
) -> ArtifactForIndexing | None:
    """One attachment version, with its extracted text read back from the object store.

    The text is not held in a column — it is written to `extracted_text_key` during extraction,
    before anything indexes it — so re-reading it here is what lets the indexing be retried at all
    without asking the student to upload the file again.

    Absent when the version, the artifact or the extracted text is gone: an attachment whose
    extraction found nothing has no text key, and there is nothing to index rather than an error.
    """
    version = await session.get(ArtifactVersion, version_id)
    if version is None or not version.extracted_text_key:
        return None
    artifact = await session.get(Artifact, version.artifact_id)
    if artifact is None:
        return None

    raw = await (store or current_store()).get_bytes(version.extracted_text_key)
    if raw is None:
        return None

    return ArtifactForIndexing(
        workspace_id=artifact.workspace_id,
        artifact_id=artifact.id,
        version_id=version.id,
        version_no=version.version_no,
        project_id=artifact.project_id,
        owner_student_id=artifact.owner_student_id,
        supported_claim=artifact.supported_claim,
        text=raw.decode("utf-8", errors="replace"),
        source_time=version.created_at,
    )
