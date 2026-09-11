"""Queries over the evidence tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.evidence.models import (
    Contribution,
    DeveloperIdentity,
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
            select(Repository).where(
                Repository.id == repository_id, visible_to(scope, Repository)
            )
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
        await session.execute(
            select(Repository).where(
                Repository.provider == provider, Repository.external_id == external_id
            )
        )
    ).scalars().first()


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
                select(ProjectRepository).where(
                    ProjectRepository.repository_id == repository_id
                )
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
        (
            await session.execute(
                select(Contribution).where(Contribution.event_id == event_id)
            )
        )
        .scalars()
        .all()
    )
