"""Evidence use cases: indexing report entries and attachments, and reading them back.

Reporting emits; evidence reacts. A submitted report and an extracted attachment become citable
references with chunks under the same access label, so the snapshot builder reads them without a
join that could forget the filter (architecture §5.7). The repository
connector that once fed this index is gone (ADR 0022).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.core.jobs import defer_after_commit
from app.core.jobs import key as job_key
from app.core.storage import ObjectStore
from app.core.types import Visibility
from app.evidence import policies  # noqa: F401  (policies register on import)
from app.evidence import repository as repo
from app.evidence.index.chunking import chunk_text
from app.evidence.models import EvidenceChunk, EvidenceSourceKind
from app.evidence.schemas import EvidenceHit, EvidenceReferenceOut
from app.reporting import artifacts as reporting_artifacts
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ the evidence index


async def index_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_kind: EvidenceSourceKind,
    source_id: UUID,
    source_version: str,
    text: str,
    visibility: Visibility,
    locator: str = "",
    project_id: UUID | None = None,
    owner_student_id: UUID | None = None,
    supported_claim: str | None = None,
    source_time: datetime | None = None,
) -> EvidenceReferenceOut:
    """Record one citable piece of evidence and index its text.

    The access label travels with the reference and onto every chunk, so retrieval filters on it
    without a join (requirements §9). Re-indexing the same source and version replaces its chunks
    rather than adding a second copy.

    Indexing is chunking and nothing else: no text leaves the host here, for any project, so a
    project marked `ai_restricted` needs no path of its own (ADR 0024).
    """
    at = source_time or now()
    reference = await repo.upsert_evidence_reference(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_student_id=owner_student_id,
        visibility=visibility,
        source_kind=source_kind,
        source_id=source_id,
        source_version=source_version,
        locator=locator,
        supported_claim=supported_claim,
        source_time=at,
    )

    chunks = chunk_text(text)
    await repo.delete_chunks(session, reference.id)
    for chunk in chunks:
        session.add(
            EvidenceChunk(
                workspace_id=workspace_id,
                evidence_ref_id=reference.id,
                project_id=project_id,
                owner_student_id=owner_student_id,
                visibility=visibility,
                source_version=source_version,
                chunk_no=chunk.chunk_no,
                text=chunk.text,
                source_time=at,
            )
        )
    await session.flush()
    return EvidenceReferenceOut.model_validate(reference)


async def search_evidence_window(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID,
    since: datetime,
    until: datetime,
) -> list[EvidenceHit]:
    """Everything in a window rather than the best matches for a query (ASSESS-01)."""
    rows = await repo.chunks_in_window(
        session, scope, project_id=project_id, since=since, until=until
    )
    return [_window_hit(chunk, reference) for chunk, reference in rows]


def _window_hit(chunk: Any, reference: Any) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=chunk.id,
        evidence_ref_id=chunk.evidence_ref_id,
        text=chunk.text,
        source_kind=reference.source_kind,
        source_id=reference.source_id,
        source_version=reference.source_version,
        locator=reference.locator,
        project_id=chunk.project_id,
        source_time=chunk.source_time,
        visibility=chunk.visibility,
    )


async def evidence_for_sources(
    session: AsyncSession,
    scope: Scope,
    *,
    source_kind: EvidenceSourceKind,
    source_ids: list[UUID],
) -> list[EvidenceHit]:
    """The evidence that came from named sources, addressed by identity rather than by time.

    The snapshot's windows are right for work that happened during a week; a report entry belongs
    to its week whenever it was sent (ASSESS-01).
    """
    rows = await repo.chunks_for_sources(
        session, scope, source_kind=source_kind, source_ids=source_ids
    )
    return [_window_hit(chunk, reference) for chunk, reference in rows]


async def chunks_for_reference(session: AsyncSession, evidence_ref_id: UUID) -> list[EvidenceChunk]:
    """Job-level read, used by the snapshot builder and by tests of the access label."""
    return await repo.chunks_for_reference(session, evidence_ref_id)


# ------------------------------------------------------------------ reactions to reporting


async def index_report_entries(session: AsyncSession, report_version_id: UUID) -> int:
    """Index one submitted version's entries. Returns how many were indexed.

    A report entry is the student's own account of their work, so it is indexed as
    `student_private` and owned by them: it supports their assessment and appears in their
    retrieval, and never in another student's (AUTH-02).

    Everything it needs is read from the version, so the inline call and the retry job in
    `evidence.tasks` do the same work from the same source. `index_evidence` upserts the reference
    and replaces its chunks, so running it twice leaves one copy.
    """
    version = await reporting_service.version_owner_for_job(session, report_version_id)
    if version is None:
        log.warning("no report version %s to index", report_version_id)
        return 0

    indexed = 0
    for entry in await reporting_service.entries_for_indexing(
        session, report_version_id=report_version_id
    ):
        await index_evidence(
            session,
            workspace_id=version.workspace_id,
            project_id=entry.project_id,
            owner_student_id=version.student_id,
            visibility=Visibility.STUDENT_PRIVATE,
            source_kind=EvidenceSourceKind.REPORT_ENTRY,
            source_id=entry.id,
            source_version=str(entry.version_no),
            locator=f"report entry, {entry.stage}",
            text=entry.text,
            source_time=entry.submitted_at,
        )
        indexed += 1
    return indexed


async def _on_report_submitted(event: Any, session: AsyncSession) -> None:
    """Index the submitted entries so an assessment has something to cite (ASSESS-01).

    Reporting emits; evidence reacts — reporting does not import evidence (architecture §4.1).

    Indexing runs inline because the chunks have to commit with the version that cites them: a job
    would let the assessment pipeline, which is also a job, read a snapshot missing the week it is
    about. `events.emit` runs handlers inside the submitting transaction with no isolation, so any
    failure while indexing — it once included a call to an embedding provider that could be down,
    rate limited or out of credit — would surface as a 500 and lose the submission.

    It cannot. The submitted version is the thing that cannot be lost (requirements §10, AC-13), so
    a failure here is caught and the work handed to a retryable job. The same trade the assessment
    enqueue makes: a thinner snapshot is recoverable — coverage and confidence describe it, and the
    professor can re-run the analysis — and an unrecorded submission is not.
    """
    try:
        await index_report_entries(session, event.report_version_id)
    except Exception:  # noqa: BLE001 - the submitted version is what must survive
        log.exception(
            "could not index the entries of report version %s inline; the report is recorded and "
            "the indexing is queued for retry",
            event.report_version_id,
        )
        _defer_reindex(session, event.report_version_id)


def _defer_reindex(session: AsyncSession, report_version_id: UUID) -> None:
    """Hand the indexing to a job, once this transaction commits.

    Deferred rather than sent now for the reason `app.core.jobs` gives: a job sent before the
    commit can be dequeued against a version that does not exist yet, and would outlive a
    submission that rolled back. Keyed on the version, so a redelivered event is one job.

    Its own failure is swallowed too. By this point the submission is what matters, and a queue
    that is briefly unreachable must not turn a recorded report into a failed request.
    """
    from app.evidence import tasks

    try:
        defer_after_commit(
            session,
            tasks.index_report_entries,
            queueing_lock=job_key("index-report", report_version_id),
            report_version_id=str(report_version_id),
        )
    except Exception:  # noqa: BLE001 - see the docstring; nothing here may reach the caller
        log.exception("could not queue the re-index of report version %s", report_version_id)


async def _index_artifact(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
    version_id: UUID,
    version_no: int,
    project_id: UUID | None,
    owner_student_id: UUID,
    supported_claim: str,
    text: str,
    source_time: Any,
) -> None:
    """One attachment version, as citable evidence.

    `student_private`, matching the artifact record itself: an attachment supports one student's
    report, and indexing it more widely would let a project-mate retrieve through search what they
    cannot open directly (AUTH-02, AC-02).
    """
    await index_evidence(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_student_id=owner_student_id,
        visibility=Visibility.STUDENT_PRIVATE,
        source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
        source_id=version_id,
        source_version=str(version_no),
        locator=f"/artifacts/{artifact_id}",
        text=text,
        supported_claim=supported_claim or None,
        source_time=source_time,
    )


async def index_artifact_version(
    session: AsyncSession, version_id: UUID, *, store: ObjectStore | None = None
) -> bool:
    """Re-index one attachment version from what is stored. False when there is nothing to index.

    The retry path. The inline one indexes the text the event already carries — re-reading it from
    the object store there would be a round trip for text we are holding, and would ignore a store
    the caller injected. By the time a retry runs the event is gone, so everything is read back
    from the version instead, which also means a stale job argument cannot make it index under the
    wrong workspace or owner.

    Absent extracted text is a no-op: an attachment that had nothing to read has nothing to index.
    """
    subject = await reporting_artifacts.version_for_indexing(session, version_id, store=store)
    if subject is None:
        return False

    await _index_artifact(
        session,
        workspace_id=subject.workspace_id,
        artifact_id=subject.artifact_id,
        version_id=subject.version_id,
        version_no=subject.version_no,
        project_id=subject.project_id,
        owner_student_id=subject.owner_student_id,
        supported_claim=subject.supported_claim,
        text=subject.text,
        source_time=subject.source_time,
    )
    return True


async def _on_artifact_extracted(event: Any, session: AsyncSession) -> None:
    """REP-04: an attachment's text becomes citable evidence the moment it is readable.

    Inline for the same reason a submitted report is: the chunks commit with the version that
    cites them, so the week's assessment does not read a snapshot missing the file uploaded to
    support it. That puts indexing on the student's upload path, and a failure there used to surface
    as a 500 — losing an attachment whose bytes were already stored and whose text was already
    extracted.

    So the failure is caught and the work handed to a retryable job. The bytes and the text are
    both in the object store by the time this runs, which is what makes the retry possible without
    the student uploading anything again.
    """
    try:
        await _index_artifact(
            session,
            workspace_id=event.workspace_id,
            artifact_id=event.artifact_id,
            version_id=event.version_id,
            version_no=event.version_no,
            project_id=event.project_id,
            owner_student_id=event.owner_student_id,
            supported_claim=event.supported_claim,
            text=event.text,
            source_time=event.source_time,
        )
    except Exception:  # noqa: BLE001 - the stored attachment is what must survive
        log.exception(
            "could not index artifact version %s inline; the attachment is stored and the "
            "indexing is queued for retry",
            event.version_id,
        )
        _defer_reindex_artifact(session, event.version_id)


def _defer_reindex_artifact(session: AsyncSession, version_id: UUID) -> None:
    """Hand the indexing to a job, once this transaction commits. Keyed on the version."""
    from app.evidence import tasks

    try:
        defer_after_commit(
            session,
            tasks.index_artifact_version,
            queueing_lock=job_key("index-artifact", version_id),
            version_id=str(version_id),
        )
    except Exception:  # noqa: BLE001 - nothing here may reach the caller
        log.exception("could not queue the re-index of artifact version %s", version_id)


async def _on_artifact_removed(event: Any, session: AsyncSession) -> None:
    """Take the withdrawn attachment out of the evidence index (requirements §11).

    Not best-effort, unlike indexing: a reference left behind is a file the next assessment can
    still quote and cite after the student removed it, which is the failure this handler exists to
    prevent. Reporting deletes the objects and the rows in the same transaction, so if this raises
    the whole removal is refused and the attachment stays — visible and indexed together, rather
    than gone from one and citable from the other.
    """
    forgotten = await repo.forget_sources(
        session,
        workspace_id=event.workspace_id,
        source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
        source_ids=event.version_ids,
    )
    log.info("forgot %d evidence reference(s) for artifact %s", forgotten, event.artifact_id)


def register_subscriptions() -> None:
    """Called on import, like the visibility policies, so any process that ingests has it wired."""
    from app.reporting import events as reporting_events

    reporting_events.subscribe(reporting_events.ReportSubmitted, _on_report_submitted)
    reporting_events.subscribe(reporting_events.ArtifactExtracted, _on_artifact_extracted)
    reporting_events.subscribe(reporting_events.ArtifactRemoved, _on_artifact_removed)


register_subscriptions()
