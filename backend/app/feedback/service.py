"""Feedback: draft, revise, attach files, publish (ADR 0026).

The rules that carry the design:

- **A professor writes, a student reads what was published.** Every write requires the professor
  role and resolves its targets through the visibility predicates of the Scope's one workspace, so a
  student, a project, a report or a feedback in another workspace is simply not found.
- **Every change is a new revision.** `Feedback.version` is the newest one and is the token callers
  hand back (`expected_version`): a stale token is a conflict, not a silent overwrite. Publishing
  points `published_version` at a revision; editing afterwards moves `version` and leaves what
  students see alone until the next publish.
- **A file is attached only once its bytes were checked.** An upload is granted as `pending`; the
  confirmation re-reads the object, compares size and SHA-256 with what was promised, checks the
  content looks like its extension, and only then makes it `ready` and part of a revision.
- **Retries do not repeat.** `create` and `publish` take an idempotency key; the first call under a
  key does the work and later ones report that outcome.
- Author and time are the backend's: nothing a client sends names them.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import orjson
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope, visible_to
from app.core.clock import now
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.ids import uuid7
from app.core.pagination import Page, clamp_limit, cursor_after, encode_cursor
from app.core.storage import (
    ObjectStore,
    PresignedUrl,
    content_type_for,
    current_store,
    extension_of,
    feedback_attachment_key,
    is_sha256_hex,
    sha256_of,
)
from app.core.types import Role
from app.feedback import policies  # noqa: F401  (policies register on import)
from app.feedback.models import (
    AttachmentState,
    Feedback,
    FeedbackAttachment,
    FeedbackIdempotency,
    FeedbackRevision,
    FeedbackRevisionAttachment,
)
from app.feedback.schemas import (
    AttachmentOut,
    FeedbackOut,
    FeedbackStatus,
    FeedbackSummary,
    ReportRefOut,
    RevisionOut,
    UploadGrantOut,
)
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting.models import (
    ProjectReportEntry,
    ReportingPeriod,
    ReportState,
    ReportVersion,
    WeeklyReport,
)

ALLOWED_EXTENSIONS = frozenset({"html", "pdf", "docx", "txt", "md"})
MAX_TITLE = 200
MAX_BODY = 50_000
MAX_REPORTS = 52
MAX_ATTACHMENTS = 20
MAX_FILENAME = 255
DOWNLOAD_TTL = 300

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def max_file_bytes() -> int:
    return get_settings().feedback_upload_max_file_mb * 1024 * 1024


def view_url(feedback_id: UUID) -> str:
    return f"{get_settings().public_url.rstrip('/')}/feedback/{feedback_id}"


# ------------------------------------------------------------------ creating and revising


async def create_feedback(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID,
    project_id: UUID,
    report_ids: Sequence[UUID],
    title: str,
    body_markdown: str,
    idempotency_key: str | None = None,
) -> FeedbackOut:
    """A new draft, revision 1. Nothing is published and nobody is told."""
    scope.require_prof()
    title = _clean_title(title)
    body_markdown = _clean_body(body_markdown)
    wanted = list(dict.fromkeys(report_ids))

    async with session.begin_nested():
        claim = await _claim(
            session,
            scope,
            operation="create",
            key=idempotency_key,
            request={
                "student_id": student_id,
                "project_id": project_id,
                "report_ids": sorted(map(str, wanted)),
                "title": title,
                "body_markdown": body_markdown,
            },
        )
        if claim is not None and claim.feedback_id is not None:
            return await get_feedback(session, scope, claim.feedback_id)

        await _require_student(session, scope, student_id)
        await projects_service.get_project(session, scope, project_id)
        checked = await _checked_reports(
            session, scope, student_id=student_id, project_id=project_id, report_ids=wanted
        )

        feedback = Feedback(
            id=uuid7(),
            workspace_id=scope.workspace_id,
            student_id=student_id,
            project_id=project_id,
            author_id=scope.user_id,
            version=0,
        )
        session.add(feedback)
        await session.flush()
        await _new_revision(
            session,
            scope,
            feedback,
            title=title,
            body_markdown=body_markdown,
            report_ids=checked,
            attachment_ids=[],
        )
        if claim is not None:
            claim.feedback_id = feedback.id
        write_audit(
            session,
            scope=scope,
            action="feedback.created",
            target_table="feedbacks",
            target_id=feedback.id,
            after={
                "student_id": str(student_id),
                "project_id": str(project_id),
                "report_ids": [str(item) for item in checked],
                "title": title,
                "version": feedback.version,
            },
        )
        await session.flush()
    return await get_feedback(session, scope, feedback.id)


async def update_feedback(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    *,
    expected_version: int,
    title: str | None = None,
    body_markdown: str | None = None,
    report_ids: Sequence[UUID] | None = None,
    remove_attachment_ids: Sequence[UUID] = (),
) -> FeedbackOut:
    """A new revision with the changes applied. What students see is untouched until `publish`."""
    scope.require_prof()
    if title is None and body_markdown is None and report_ids is None and not remove_attachment_ids:
        raise ValidationError("nothing to update: give a title, body, reports or files to remove")
    feedback = await _locked(session, scope, feedback_id)
    _require_current(feedback, expected_version)
    head = await _revision(session, scope, feedback.id, feedback.version)
    carried = await _attachment_ids(session, head.id)

    new_title = _clean_title(title) if title is not None else head.title
    new_body = _clean_body(body_markdown) if body_markdown is not None else head.body_markdown
    new_reports = list(head.report_ids)
    if report_ids is not None:
        new_reports = await _checked_reports(
            session,
            scope,
            student_id=feedback.student_id,
            project_id=feedback.project_id,
            report_ids=list(dict.fromkeys(report_ids)),
        )
    removing = set(remove_attachment_ids)
    unknown = removing - set(carried)
    if unknown:
        raise ValidationError("a file to remove is not attached to this feedback")
    kept = [item for item in carried if item not in removing]

    before_version = feedback.version
    await _new_revision(
        session,
        scope,
        feedback,
        title=new_title,
        body_markdown=new_body,
        report_ids=new_reports,
        attachment_ids=kept,
    )
    changed = [
        name
        for name, differs in (
            ("title", new_title != head.title),
            ("body_markdown", new_body != head.body_markdown),
            ("report_ids", new_reports != list(head.report_ids)),
            ("attachments", bool(removing)),
        )
        if differs
    ]
    write_audit(
        session,
        scope=scope,
        action="feedback.updated",
        target_table="feedbacks",
        target_id=feedback.id,
        before={"version": before_version},
        after={"version": feedback.version, "changed": changed},
    )
    await session.flush()
    return await get_feedback(session, scope, feedback.id)


async def publish_feedback(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    *,
    expected_version: int,
    notify_student: bool = False,
    idempotency_key: str | None = None,
) -> FeedbackOut:
    """Make the revision the caller reviewed the one the student reads.

    `expected_version` is the revision the caller looked at: if the draft moved since, publishing
    would show the student something nobody reviewed, so it is a conflict instead.
    """
    scope.require_prof()
    if notify_student:
        # Refused rather than ignored: a caller who asked for a notification and got none would
        # believe the student had been told.
        raise ValidationError(
            "notifying the student on publish is not available yet; publish with "
            "notify_student=false"
        )
    async with session.begin_nested():
        claim = await _claim(
            session,
            scope,
            operation="publish",
            key=idempotency_key,
            request={"feedback_id": feedback_id, "expected_version": expected_version},
        )
        if claim is not None and claim.feedback_id is not None:
            return await get_feedback(session, scope, claim.feedback_id)

        feedback = await _locked(session, scope, feedback_id)
        _require_current(feedback, expected_version)
        if claim is not None:
            claim.feedback_id = feedback.id
        if feedback.published_version == feedback.version:
            return await get_feedback(session, scope, feedback.id)  # already shown; nothing to do

        revision = await _revision(session, scope, feedback.id, feedback.version)
        stamp = now()
        previous = feedback.published_version
        revision.published_at = stamp
        revision.published_by = scope.user_id
        feedback.published_version = feedback.version
        feedback.published_at = stamp
        feedback.updated_at = stamp
        write_audit(
            session,
            scope=scope,
            action="feedback.published",
            target_table="feedbacks",
            target_id=feedback.id,
            before={"published_version": previous},
            after={
                "published_version": feedback.version,
                "student_id": str(feedback.student_id),
            },
        )
        await session.flush()
    return await get_feedback(session, scope, feedback.id)


# ------------------------------------------------------------------ files


async def request_attachment_upload(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    *,
    filename: str,
    byte_size: int,
    sha256: str,
    store: ObjectStore | None = None,
) -> UploadGrantOut:
    """Permission to write one object. Records a `pending` file that nothing shows yet."""
    scope.require_prof()
    feedback = await _locked(session, scope, feedback_id)
    clean_name = _clean_filename(filename)
    _require_attachable_type(clean_name)
    if byte_size <= 0:
        raise ValidationError("an empty file cannot be attached")
    if byte_size > max_file_bytes():
        limit = get_settings().feedback_upload_max_file_mb
        raise ValidationError(f"this file is larger than the {limit} MB per-file limit")
    if not is_sha256_hex(sha256):
        raise ValidationError("sha256 must be the file's SHA-256 as 64 lowercase hex characters")
    head = await _revision(session, scope, feedback.id, feedback.version)
    if len(await _attachment_ids(session, head.id)) >= MAX_ATTACHMENTS:
        raise ValidationError(f"a feedback carries at most {MAX_ATTACHMENTS} files")

    attachment_id = uuid7()
    key = feedback_attachment_key(
        workspace_id=scope.workspace_id,
        feedback_id=feedback.id,
        attachment_id=attachment_id,
        sha256=sha256,
        filename=clean_name,
    )
    content_type = content_type_for(clean_name)
    session.add(
        FeedbackAttachment(
            id=attachment_id,
            workspace_id=scope.workspace_id,
            feedback_id=feedback.id,
            filename=clean_name,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            storage_key=key,
            state=AttachmentState.PENDING.value,
            created_by=scope.user_id,
        )
    )
    await session.flush()
    presigned = await (store or current_store()).presigned_put(key, content_type=content_type)
    write_audit(
        session,
        scope=scope,
        action="feedback.upload_requested",
        target_table="feedback_attachments",
        target_id=attachment_id,
        after={
            "feedback_id": str(feedback.id),
            "filename": clean_name,
            "byte_size": byte_size,
        },
    )
    return UploadGrantOut(
        attachment_id=attachment_id,
        filename=clean_name,
        upload_url=presigned.url,
        upload_headers=presigned.headers,
        expires_in=presigned.expires_in,
    )


async def confirm_attachment(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    attachment_id: UUID,
    *,
    expected_version: int | None = None,
    store: ObjectStore | None = None,
) -> FeedbackOut:
    """Verify what arrived, then attach it: a grant becomes a fact only here.

    Size and checksum are recomputed from the stored object, not read from the request. A file
    that fails is deleted from storage and stays `pending`, which nothing ever lists, so a failed
    upload leaves no attachment behind. Confirming a file that is already attached changes nothing.
    """
    scope.require_prof()
    feedback = await _locked(session, scope, feedback_id)
    attachment = (
        await session.execute(
            select(FeedbackAttachment).where(
                FeedbackAttachment.id == attachment_id,
                FeedbackAttachment.feedback_id == feedback.id,
                visible_to(scope, FeedbackAttachment),
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("attachment not found")
    if attachment.state == AttachmentState.READY.value:
        return await get_feedback(session, scope, feedback.id)
    if expected_version is not None:
        _require_current(feedback, expected_version)

    active = store or current_store()
    info = await active.head(attachment.storage_key)
    if info is None:
        raise ValidationError("no object was uploaded to the granted location")
    if info.byte_size > max_file_bytes():
        await active.delete(attachment.storage_key)
        limit = get_settings().feedback_upload_max_file_mb
        raise ValidationError(f"this file is larger than the {limit} MB per-file limit")
    data = await active.get_bytes(attachment.storage_key)
    if data is None:
        raise ValidationError("no object was uploaded to the granted location")
    problem = _content_problem(attachment.filename, data)
    if len(data) != attachment.byte_size:
        problem = "the uploaded file's size does not match the one declared"
    elif sha256_of(data) != attachment.sha256:
        problem = "the uploaded file's checksum does not match the one declared"
    if problem is not None:
        await active.delete(attachment.storage_key)
        raise ValidationError(problem)

    head = await _revision(session, scope, feedback.id, feedback.version)
    carried = await _attachment_ids(session, head.id)
    if len(carried) >= MAX_ATTACHMENTS:
        await active.delete(attachment.storage_key)
        raise ValidationError(f"a feedback carries at most {MAX_ATTACHMENTS} files")
    attachment.state = AttachmentState.READY.value
    attachment.confirmed_at = now()
    await _new_revision(
        session,
        scope,
        feedback,
        title=head.title,
        body_markdown=head.body_markdown,
        report_ids=list(head.report_ids),
        attachment_ids=[*carried, attachment.id],
    )
    write_audit(
        session,
        scope=scope,
        action="feedback.attachment_added",
        target_table="feedback_attachments",
        target_id=attachment.id,
        after={
            "feedback_id": str(feedback.id),
            "filename": attachment.filename,
            "byte_size": attachment.byte_size,
            "sha256": attachment.sha256,
            "version": feedback.version,
        },
    )
    await session.flush()
    return await get_feedback(session, scope, feedback.id)


async def upload_attachment_inline(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    *,
    filename: str,
    content: bytes,
    expected_version: int | None = None,
    store: ObjectStore | None = None,
) -> FeedbackOut:
    """For a caller that cannot PUT to a presigned URL: small bytes in the call, same checks.

    It is the two-step upload run back to back, so there is one path that decides what a valid file
    is. The server computes the checksum, which means it verifies integrity of storage only; a
    client that wants end-to-end proof uses the presigned flow and declares its own digest.
    """
    limit = get_settings().feedback_inline_upload_max_mb * 1024 * 1024
    if len(content) > limit:
        raise ValidationError(
            f"too large to send inline (limit {get_settings().feedback_inline_upload_max_mb} MB); "
            "request an upload URL instead"
        )
    grant = await request_attachment_upload(
        session,
        scope,
        feedback_id,
        filename=filename,
        byte_size=len(content),
        sha256=sha256_of(content),
        store=store,
    )
    key = (
        await session.execute(
            select(FeedbackAttachment.storage_key).where(
                FeedbackAttachment.id == grant.attachment_id
            )
        )
    ).scalar_one()
    active = store or current_store()
    await active.put_bytes(key, content, content_type=content_type_for(grant.filename))
    return await confirm_attachment(
        session,
        scope,
        feedback_id,
        grant.attachment_id,
        expected_version=expected_version,
        store=active,
    )


async def attachment_download(
    session: AsyncSession,
    scope: Scope,
    attachment_id: UUID,
    *,
    store: ObjectStore | None = None,
) -> tuple[FeedbackAttachment, PresignedUrl]:
    """A private, expiring link — and only for a file the caller may read.

    The store sets `Content-Disposition: attachment`, so an uploaded .html is downloaded, never
    rendered in the storage origin.
    """
    attachment = await _readable_attachment(session, scope, attachment_id)
    link = await (store or current_store()).presigned_get(
        attachment.storage_key, expires_in=DOWNLOAD_TTL, filename=attachment.filename
    )
    return attachment, link


# ------------------------------------------------------------------ reads


async def get_feedback(
    session: AsyncSession,
    scope: Scope,
    feedback_id: UUID,
    *,
    version: int | None = None,
    with_download_urls: bool = False,
    store: ObjectStore | None = None,
) -> FeedbackOut:
    """A professor sees the newest revision (or any earlier `version`); a student, the published."""
    feedback = (
        await session.execute(
            select(Feedback).where(Feedback.id == feedback_id, visible_to(scope, Feedback))
        )
    ).scalar_one_or_none()
    if feedback is None:
        raise NotFoundError("feedback not found")
    if scope.is_prof:
        shown = version if version is not None else feedback.version
    else:
        shown = feedback.published_version or 0
    revision = await _revision(session, scope, feedback.id, shown)
    attachments = await _attachments_of(session, scope, revision.id)

    out_attachments: list[AttachmentOut] = []
    for attachment in attachments:
        item = AttachmentOut(
            attachment_id=attachment.id,
            filename=attachment.filename,
            content_type=attachment.content_type,
            byte_size=attachment.byte_size,
            sha256=attachment.sha256,
        )
        if with_download_urls:
            link = await (store or current_store()).presigned_get(
                attachment.storage_key, expires_in=DOWNLOAD_TTL, filename=attachment.filename
            )
            item.download_url = link.url
            item.download_expires_in = link.expires_in
        out_attachments.append(item)

    return FeedbackOut(
        feedback_id=feedback.id,
        workspace_id=feedback.workspace_id,
        student_id=feedback.student_id,
        project_id=feedback.project_id,
        report_ids=list(revision.report_ids),
        reports=await _report_refs(session, scope, list(revision.report_ids)),
        title=revision.title,
        body_markdown=revision.body_markdown,
        version=revision.version_no,
        status=_status(feedback),
        published_version=feedback.published_version,
        has_unpublished_changes=_has_unpublished_changes(scope, feedback),
        attachments=out_attachments,
        created_by=feedback.author_id,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
        published_at=feedback.published_at,
        view_url=view_url(feedback.id),
    )


async def list_revisions(
    session: AsyncSession, scope: Scope, feedback_id: UUID
) -> list[RevisionOut]:
    """The history of one feedback, oldest first. A professor's view: students get no history."""
    scope.require_prof()
    feedback = (
        await session.execute(
            select(Feedback).where(Feedback.id == feedback_id, visible_to(scope, Feedback))
        )
    ).scalar_one_or_none()
    if feedback is None:
        raise NotFoundError("feedback not found")
    revisions = (
        (
            await session.execute(
                select(FeedbackRevision)
                .where(
                    FeedbackRevision.feedback_id == feedback.id,
                    visible_to(scope, FeedbackRevision),
                )
                .order_by(FeedbackRevision.version_no)
            )
        )
        .scalars()
        .all()
    )
    return [
        RevisionOut(
            version=row.version_no,
            title=row.title,
            report_ids=list(row.report_ids),
            attachment_ids=await _attachment_ids(session, row.id),
            created_by=row.author_id,
            created_at=row.created_at,
            published_at=row.published_at,
        )
        for row in revisions
    ]


async def list_feedback(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    report_id: UUID | None = None,
    status: FeedbackStatus | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[FeedbackSummary]:
    """Newest first. A student's list holds only what was published to them, as published."""
    size = clamp_limit(limit)
    after = cursor_after(cursor)
    shown = Feedback.version if scope.is_prof else Feedback.published_version
    query = (
        select(Feedback, FeedbackRevision)
        .join(
            FeedbackRevision,
            (FeedbackRevision.feedback_id == Feedback.id) & (FeedbackRevision.version_no == shown),
        )
        .where(visible_to(scope, Feedback))
    )
    if student_id is not None:
        query = query.where(Feedback.student_id == student_id)
    if project_id is not None:
        query = query.where(Feedback.project_id == project_id)
    if report_id is not None:
        query = query.where(FeedbackRevision.report_ids.contains([report_id]))
    if status == "draft":
        query = query.where(Feedback.published_version.is_(None))
    elif status == "published":
        query = query.where(Feedback.published_version.is_not(None))
    if after is not None:
        query = query.where(Feedback.id < after)
    rows = (await session.execute(query.order_by(Feedback.id.desc()).limit(size + 1))).all()

    page, more = rows[:size], len(rows) > size
    items = []
    for feedback, revision in page:
        count = (
            await session.execute(
                select(func.count()).where(
                    FeedbackRevisionAttachment.revision_id == revision.id,
                    visible_to(scope, FeedbackRevisionAttachment),
                )
            )
        ).scalar_one()
        items.append(
            FeedbackSummary(
                feedback_id=feedback.id,
                student_id=feedback.student_id,
                project_id=feedback.project_id,
                report_ids=list(revision.report_ids),
                title=revision.title,
                version=revision.version_no,
                status=_status(feedback),
                published_version=feedback.published_version,
                has_unpublished_changes=_has_unpublished_changes(scope, feedback),
                attachment_count=int(count),
                updated_at=feedback.updated_at,
                published_at=feedback.published_at,
                view_url=view_url(feedback.id),
            )
        )
    next_cursor = encode_cursor({"after": str(page[-1][0].id)}) if more else None
    return Page(items=items, next_cursor=next_cursor, limit=size)


# ------------------------------------------------------------------ internals


def _status(feedback: Feedback) -> FeedbackStatus:
    return "published" if feedback.published_version is not None else "draft"


def _has_unpublished_changes(scope: Scope, feedback: Feedback) -> bool:
    """Only a professor is told a draft exists beyond what the student reads."""
    return (
        scope.is_prof
        and feedback.published_version is not None
        and feedback.version > feedback.published_version
    )


def _clean_title(title: str) -> str:
    cleaned = _CONTROL.sub(" ", title).strip()
    if not cleaned:
        raise ValidationError("a feedback needs a title")
    if len(cleaned) > MAX_TITLE:
        raise ValidationError(f"the title is longer than {MAX_TITLE} characters")
    return cleaned


def _clean_body(body: str) -> str:
    if not body.strip():
        raise ValidationError("a feedback needs a body")
    if len(body) > MAX_BODY:
        raise ValidationError(f"the body is longer than {MAX_BODY} characters")
    return body


def _clean_filename(filename: str) -> str:
    """A display name: the last path segment, without control characters.

    Never used as a path. The storage key is built from ids and the checksum, and takes only the
    extension from here, and only a recognised one.
    """
    leaf = re.split(r"[\\/]", _CONTROL.sub("", filename))[-1].strip().strip(".")
    if not leaf:
        raise ValidationError("a file needs a name")
    if len(leaf) > MAX_FILENAME:
        raise ValidationError(f"the file name is longer than {MAX_FILENAME} characters")
    return leaf


def _require_attachable_type(filename: str) -> None:
    if extension_of(filename) not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(f".{ext}" for ext in sorted(ALLOWED_EXTENSIONS))
        raise ValidationError(f"this kind of file cannot be attached; allowed: {allowed}")


def _content_problem(filename: str, data: bytes) -> str | None:
    """Whether the bytes are plausibly what the extension says. Not a malware scan.

    It stops a renamed executable or an empty file being kept as a PDF; it does not make HTML safe,
    which is why HTML is only ever offered as a download.
    """
    extension = extension_of(filename)
    if extension not in ALLOWED_EXTENSIONS:
        return "this kind of file cannot be attached"
    if extension == "pdf":
        return None if data.lstrip(b"\x00 \t\r\n")[:5] == b"%PDF-" else "this is not a PDF file"
    if extension == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return None
        except zipfile.BadZipFile:
            pass
        return "this is not a Word (.docx) file"
    if b"\x00" in data:
        return "this is not a text file"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "a text file must be UTF-8"
    return None


def _require_current(feedback: Feedback, expected_version: int) -> None:
    if feedback.version != expected_version:
        raise ConflictError(
            f"this feedback is at version {feedback.version}, not {expected_version}: read it "
            "again and apply your change to that version",
            current_version=feedback.version,
        )


async def _require_student(session: AsyncSession, scope: Scope, student_id: UUID) -> None:
    try:
        student = await identity_service.get_user(session, scope, student_id)
    except NotFoundError:
        raise NotFoundError("student not found") from None
    if student.role is not Role.STUDENT:
        raise ValidationError("student_id must name a student")


async def _checked_reports(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID,
    project_id: UUID,
    report_ids: list[UUID],
) -> list[UUID]:
    """These must be the student's own submitted reports, with a section on this project.

    One message for "no such report", "someone else's report" and "another workspace's", so the
    answer does not tell a caller which ids exist.
    """
    if not report_ids:
        raise ValidationError("a feedback is about at least one weekly report")
    if len(report_ids) > MAX_REPORTS:
        raise ValidationError(f"a feedback can cover at most {MAX_REPORTS} reports")
    rows = {
        row.id: row
        for row in (
            await session.execute(
                select(WeeklyReport.id, WeeklyReport.student_id, WeeklyReport.workflow_state).where(
                    WeeklyReport.id.in_(report_ids), visible_to(scope, WeeklyReport)
                )
            )
        ).all()
    }
    for report_id in report_ids:
        row = rows.get(report_id)
        if row is None or row.student_id != student_id:
            raise ValidationError(f"report {report_id} was not found for this student")
        if row.workflow_state is ReportState.DRAFT:
            raise ValidationError(f"report {report_id} has not been submitted")
    on_project = set(
        (
            await session.execute(
                select(ReportVersion.report_id)
                .join(ProjectReportEntry, ProjectReportEntry.report_version_id == ReportVersion.id)
                .where(
                    ReportVersion.report_id.in_(report_ids),
                    ProjectReportEntry.project_id == project_id,
                    scope.within(ProjectReportEntry.workspace_id),
                )
            )
        ).scalars()
    )
    for report_id in report_ids:
        if report_id not in on_project:
            raise ValidationError(f"report {report_id} has no section on this project")
    return report_ids


async def _report_refs(
    session: AsyncSession, scope: Scope, report_ids: list[UUID]
) -> list[ReportRefOut]:
    if not report_ids:
        return []
    rows = (
        await session.execute(
            select(
                WeeklyReport.id,
                ReportingPeriod.id,
                ReportingPeriod.local_start,
                ReportingPeriod.local_end,
            )
            .join(ReportingPeriod, ReportingPeriod.id == WeeklyReport.period_id)
            .where(WeeklyReport.id.in_(report_ids), scope.within(WeeklyReport.workspace_id))
            .order_by(ReportingPeriod.local_start)
        )
    ).all()
    return [
        ReportRefOut(
            report_id=row[0],
            period_id=row[1],
            local_start=row[2].isoformat(),
            local_end=row[3].isoformat(),
        )
        for row in rows
    ]


async def _locked(session: AsyncSession, scope: Scope, feedback_id: UUID) -> Feedback:
    """The feedback row, locked for the transaction: concurrent writers take turns."""
    feedback = (
        await session.execute(
            select(Feedback)
            .where(Feedback.id == feedback_id, visible_to(scope, Feedback))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if feedback is None:
        raise NotFoundError("feedback not found")
    return feedback


async def _revision(
    session: AsyncSession, scope: Scope, feedback_id: UUID, version: int
) -> FeedbackRevision:
    revision = (
        await session.execute(
            select(FeedbackRevision).where(
                FeedbackRevision.feedback_id == feedback_id,
                FeedbackRevision.version_no == version,
                visible_to(scope, FeedbackRevision),
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise NotFoundError("feedback version not found")
    return revision


async def _new_revision(
    session: AsyncSession,
    scope: Scope,
    feedback: Feedback,
    *,
    title: str,
    body_markdown: str,
    report_ids: list[UUID],
    attachment_ids: list[UUID],
) -> FeedbackRevision:
    feedback.version += 1
    feedback.updated_at = now()
    revision = FeedbackRevision(
        id=uuid7(),
        workspace_id=feedback.workspace_id,
        feedback_id=feedback.id,
        version_no=feedback.version,
        title=title,
        body_markdown=body_markdown,
        report_ids=report_ids,
        author_id=scope.user_id,
    )
    session.add(revision)
    await session.flush()
    for attachment_id in attachment_ids:
        session.add(
            FeedbackRevisionAttachment(
                workspace_id=feedback.workspace_id,
                revision_id=revision.id,
                attachment_id=attachment_id,
            )
        )
    await session.flush()
    return revision


async def _attachment_ids(session: AsyncSession, revision_id: UUID) -> list[UUID]:
    return list(
        (
            await session.execute(
                select(FeedbackRevisionAttachment.attachment_id)
                .join(
                    FeedbackAttachment,
                    FeedbackAttachment.id == FeedbackRevisionAttachment.attachment_id,
                )
                .where(FeedbackRevisionAttachment.revision_id == revision_id)
                .order_by(FeedbackAttachment.created_at, FeedbackAttachment.id)
            )
        ).scalars()
    )


async def _attachments_of(
    session: AsyncSession, scope: Scope, revision_id: UUID
) -> list[FeedbackAttachment]:
    return list(
        (
            await session.execute(
                select(FeedbackAttachment)
                .join(
                    FeedbackRevisionAttachment,
                    FeedbackRevisionAttachment.attachment_id == FeedbackAttachment.id,
                )
                .where(
                    FeedbackRevisionAttachment.revision_id == revision_id,
                    FeedbackAttachment.state == AttachmentState.READY.value,
                    visible_to(scope, FeedbackAttachment),
                )
                .order_by(FeedbackAttachment.created_at, FeedbackAttachment.id)
            )
        ).scalars()
    )


async def _readable_attachment(
    session: AsyncSession, scope: Scope, attachment_id: UUID
) -> FeedbackAttachment:
    attachment = (
        await session.execute(
            select(FeedbackAttachment).where(
                FeedbackAttachment.id == attachment_id,
                FeedbackAttachment.state == AttachmentState.READY.value,
                visible_to(scope, FeedbackAttachment),
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("attachment not found")
    return attachment


async def _claim(
    session: AsyncSession,
    scope: Scope,
    *,
    operation: str,
    key: str | None,
    request: dict[str, Any],
) -> FeedbackIdempotency | None:
    """Take an idempotency key, or find the call that already holds it.

    Returns None when no key was given. Otherwise returns the key's row: freshly inserted (its
    `feedback_id` is None until the caller fills it) or the earlier call's, which the caller
    replays. The insert is `ON CONFLICT DO NOTHING`, so two concurrent first calls do not both
    proceed: the second waits for the first to commit and then sees its row. A key reused for a
    different request is refused rather than answered with the wrong feedback. Callers run this in
    a savepoint, so a call that then fails leaves no claim behind.
    """
    if key is None:
        return None
    if not 1 <= len(key) <= 200:
        raise ValidationError("idempotency_key must be 1 to 200 characters")
    fingerprint = hashlib.sha256(
        orjson.dumps(request, option=orjson.OPT_SORT_KEYS, default=str)
    ).hexdigest()
    inserted = (
        await session.execute(
            pg_insert(FeedbackIdempotency)
            .values(
                id=uuid7(),
                workspace_id=scope.workspace_id,
                actor_id=scope.user_id,
                operation=operation,
                key=key,
                request_hash=fingerprint,
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "actor_id", "operation", "key"])
            .returning(FeedbackIdempotency.id)
        )
    ).scalar_one_or_none()
    row = (
        await session.execute(
            select(FeedbackIdempotency)
            .where(
                FeedbackIdempotency.workspace_id == scope.workspace_id,
                FeedbackIdempotency.actor_id == scope.user_id,
                FeedbackIdempotency.operation == operation,
                FeedbackIdempotency.key == key,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if inserted is None and row.request_hash != fingerprint:
        raise ConflictError("this idempotency_key was already used for a different request")
    return row
