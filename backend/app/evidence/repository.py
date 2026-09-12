"""Queries over the evidence tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.ids import uuid7
from app.evidence.models import (
    ConnectionState,
    Contribution,
    DeveloperIdentity,
    EvidenceChunk,
    EvidenceReference,
    ProjectRepository,
    Repository,
    RepositoryEvent,
    SyncRun,
    SyncState,
)


async def get_repository(
    session: AsyncSession, scope: Scope, repository_id: UUID
) -> Repository | None:
    return (
        await session.execute(
            select(Repository).where(Repository.id == repository_id, visible_to(scope, Repository))
        )
    ).scalar_one_or_none()


async def get_by_external_id(
    session: AsyncSession, workspace_id: UUID, provider: str, external_id: str
) -> Repository | None:
    return (
        await session.execute(
            select(Repository).where(
                Repository.workspace_id == workspace_id,
                Repository.provider == provider,
                Repository.external_id == external_id,
            )
        )
    ).scalar_one_or_none()


async def get_by_external_id_any_workspace(
    session: AsyncSession, provider: str, external_id: str
) -> Repository | None:
    """A webhook arrives before we know who it is for: it is authenticated by its signature."""
    return (
        (
            await session.execute(
                select(Repository).where(
                    Repository.provider == provider, Repository.external_id == external_id
                )
            )
        )
        .scalars()
        .first()
    )


async def list_repositories(
    session: AsyncSession, scope: Scope, *, project_id: UUID | None = None
) -> list[Repository]:
    statement = (
        select(Repository).where(visible_to(scope, Repository)).order_by(Repository.full_name)
    )
    if project_id is not None:
        statement = statement.where(
            Repository.id.in_(
                select(ProjectRepository.repository_id).where(
                    ProjectRepository.project_id == project_id
                )
            )
        )
    return list((await session.execute(statement)).scalars().all())


async def get_project_link(
    session: AsyncSession, repository_id: UUID, project_id: UUID
) -> ProjectRepository | None:
    return (
        await session.execute(
            select(ProjectRepository).where(
                ProjectRepository.repository_id == repository_id,
                ProjectRepository.project_id == project_id,
            )
        )
    ).scalar_one_or_none()


async def list_project_links(
    session: AsyncSession, scope: Scope, repository_id: UUID
) -> list[ProjectRepository]:
    return list(
        (
            await session.execute(
                select(ProjectRepository)
                .where(
                    ProjectRepository.repository_id == repository_id,
                    visible_to(scope, ProjectRepository),
                )
                .order_by(ProjectRepository.created_at)
            )
        )
        .scalars()
        .all()
    )


async def links_for_repository(
    session: AsyncSession, repository_id: UUID
) -> list[ProjectRepository]:
    """Job-level read: attribution runs in the worker, which has no Scope."""
    return list(
        (
            await session.execute(
                select(ProjectRepository).where(ProjectRepository.repository_id == repository_id)
            )
        )
        .scalars()
        .all()
    )


async def last_run(session: AsyncSession, repository_id: UUID) -> SyncRun | None:
    return (
        await session.execute(
            select(SyncRun)
            .where(SyncRun.repository_id == repository_id)
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def last_completed_run(session: AsyncSession, repository_id: UUID) -> SyncRun | None:
    """The watermark to continue from: a partial run advanced to its last good page."""
    return (
        await session.execute(
            select(SyncRun)
            .where(
                SyncRun.repository_id == repository_id,
                SyncRun.state.in_((SyncState.COMPLETED, SyncState.PARTIAL)),
            )
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def attempt_number(session: AsyncSession, repository_id: UUID) -> int:
    count = (
        await session.execute(
            select(func.count(SyncRun.id)).where(SyncRun.repository_id == repository_id)
        )
    ).scalar_one()
    return int(count) + 1


async def clear_watermarks(session: AsyncSession, repository_id: UUID) -> None:
    await session.execute(
        update(SyncRun).where(SyncRun.repository_id == repository_id).values(watermark={})
    )
    await session.flush()


async def list_events(
    session: AsyncSession,
    scope: Scope,
    *,
    repository_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[RepositoryEvent]:
    statement = (
        select(RepositoryEvent)
        .where(visible_to(scope, RepositoryEvent))
        .order_by(RepositoryEvent.event_at, RepositoryEvent.id)
    )
    if repository_id is not None:
        statement = statement.where(RepositoryEvent.repository_id == repository_id)
    if since is not None:
        statement = statement.where(RepositoryEvent.event_at >= since)
    if until is not None:
        statement = statement.where(RepositoryEvent.event_at < until)
    return list((await session.execute(statement)).scalars().all())


async def events_for_attribution(
    session: AsyncSession, repository_id: UUID, *, since: datetime | None = None
) -> list[RepositoryEvent]:
    """Job-level read: resolving contributions runs in the worker."""
    statement = (
        select(RepositoryEvent)
        .where(RepositoryEvent.repository_id == repository_id)
        .order_by(RepositoryEvent.event_at)
    )
    if since is not None:
        statement = statement.where(RepositoryEvent.ingested_at >= since)
    return list((await session.execute(statement)).scalars().all())


async def mark_versions_unavailable(
    session: AsyncSession, repository_id: UUID, versions: list[str]
) -> None:
    """REPO-06: the retained snapshot stays; only the liveness flag changes."""
    if not versions:
        return
    await session.execute(
        update(RepositoryEvent)
        .where(
            RepositoryEvent.repository_id == repository_id,
            RepositoryEvent.source_version.in_(versions),
        )
        .values(live_available=False)
    )
    await session.flush()


# ------------------------------------------------------------------ identities and contributions


async def identities_for_workspace(
    session: AsyncSession, workspace_id: UUID, provider: str
) -> list[DeveloperIdentity]:
    return list(
        (
            await session.execute(
                select(DeveloperIdentity).where(
                    DeveloperIdentity.workspace_id == workspace_id,
                    DeveloperIdentity.provider == provider,
                )
            )
        )
        .scalars()
        .all()
    )


async def identities_for_repository_workspace(
    session: AsyncSession, repository_id: UUID
) -> list[DeveloperIdentity]:
    """Job-level read: attribution runs in the worker and needs the whole mapping table."""
    repository = await session.get(Repository, repository_id)
    if repository is None:
        return []
    return await identities_for_workspace(session, repository.workspace_id, repository.provider)


async def find_identity(
    session: AsyncSession,
    workspace_id: UUID,
    provider: str,
    login: str | None,
    email: str | None,
) -> DeveloperIdentity | None:
    statement = select(DeveloperIdentity).where(
        DeveloperIdentity.workspace_id == workspace_id, DeveloperIdentity.provider == provider
    )
    if login is not None:
        statement = statement.where(DeveloperIdentity.login == login)
    elif email is not None:
        statement = statement.where(DeveloperIdentity.email == email)
    else:
        return None
    return (await session.execute(statement)).scalars().first()


async def distinct_contributed_events(
    session: AsyncSession, scope: Scope, *, project_id: UUID
) -> int:
    """AC-06: count the artifact once, however many students share it."""
    return (
        await session.execute(
            select(func.count(func.distinct(Contribution.event_id))).where(
                Contribution.project_id == project_id, visible_to(scope, Contribution)
            )
        )
    ).scalar_one()


async def get_identity(
    session: AsyncSession, scope: Scope, identity_id: UUID
) -> DeveloperIdentity | None:
    return (
        await session.execute(
            select(DeveloperIdentity).where(
                DeveloperIdentity.id == identity_id, visible_to(scope, DeveloperIdentity)
            )
        )
    ).scalar_one_or_none()


async def list_identities(
    session: AsyncSession, scope: Scope, *, student_id: UUID | None = None
) -> list[DeveloperIdentity]:
    statement = (
        select(DeveloperIdentity)
        .where(visible_to(scope, DeveloperIdentity))
        .order_by(DeveloperIdentity.created_at)
    )
    if student_id is not None:
        statement = statement.where(DeveloperIdentity.student_id == student_id)
    return list((await session.execute(statement)).scalars().all())


async def upsert_evidence_reference(session: AsyncSession, **values: object) -> EvidenceReference:
    """One reference per (source kind, id, version): re-indexing updates rather than duplicates."""
    statement = (
        insert(EvidenceReference)
        .values(id=uuid7(), **values)
        .on_conflict_do_update(
            index_elements=["source_kind", "source_id", "source_version"],
            set_={
                "project_id": values.get("project_id"),
                "owner_student_id": values.get("owner_student_id"),
                "visibility": values.get("visibility"),
                "locator": values.get("locator"),
                "supported_claim": values.get("supported_claim"),
                "source_time": values.get("source_time"),
            },
        )
        .returning(EvidenceReference)
    )
    reference = (await session.execute(statement)).scalar_one()
    await session.flush()
    return reference


async def delete_chunks(session: AsyncSession, evidence_ref_id: UUID) -> None:
    await session.execute(
        delete(EvidenceChunk).where(EvidenceChunk.evidence_ref_id == evidence_ref_id)
    )


async def chunks_for_reference(session: AsyncSession, evidence_ref_id: UUID) -> list[EvidenceChunk]:
    return list(
        (
            await session.execute(
                select(EvidenceChunk)
                .where(EvidenceChunk.evidence_ref_id == evidence_ref_id)
                .order_by(EvidenceChunk.chunk_no)
            )
        )
        .scalars()
        .all()
    )


async def chunks_in_window(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID,
    since: datetime,
    until: datetime,
) -> list[tuple[EvidenceChunk, EvidenceReference]]:
    """Everything the caller may see in a window, for the snapshot builder (ASSESS-01)."""
    from app.evidence.index.retrieval import visible_chunks

    rows = await session.execute(
        select(EvidenceChunk, EvidenceReference)
        .join(EvidenceReference, EvidenceReference.id == EvidenceChunk.evidence_ref_id)
        .where(
            visible_chunks(scope),
            EvidenceChunk.project_id == project_id,
            EvidenceChunk.source_time >= since,
            EvidenceChunk.source_time < until,
        )
        .order_by(EvidenceChunk.source_time, EvidenceChunk.chunk_no)
    )
    return [(chunk, reference) for chunk, reference in rows]


async def list_contributions(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
) -> list[Contribution]:
    statement = (
        select(Contribution)
        .where(visible_to(scope, Contribution))
        .order_by(Contribution.created_at, Contribution.id)
    )
    if student_id is not None:
        statement = statement.where(Contribution.student_id == student_id)
    if project_id is not None:
        statement = statement.where(Contribution.project_id == project_id)
    return list((await session.execute(statement)).scalars().all())


async def contributions_for_event(session: AsyncSession, event_id: UUID) -> list[Contribution]:
    return list(
        (await session.execute(select(Contribution).where(Contribution.event_id == event_id)))
        .scalars()
        .all()
    )


async def connected_repositories(session: AsyncSession) -> list[Repository]:
    """Every repository the worker should sync, across every workspace.

    Job-level read with no Scope: the incremental sync runs on a schedule, not on behalf of anyone.
    `unauthorized` rows are skipped — a revoked credential needs a person, and retrying it every
    thirty minutes only fills the log (REPO-05, architecture §8.3).
    """
    return list(
        (
            await session.execute(
                select(Repository)
                .where(Repository.connection_state == ConnectionState.CONNECTED)
                .order_by(Repository.workspace_id, Repository.full_name)
            )
        )
        .scalars()
        .all()
    )


async def get_evidence_reference(
    session: AsyncSession, scope: Scope, reference_id: UUID
) -> EvidenceReference | None:
    return (
        await session.execute(
            select(EvidenceReference).where(
                EvidenceReference.id == reference_id, visible_to(scope, EvidenceReference)
            )
        )
    ).scalar_one_or_none()
