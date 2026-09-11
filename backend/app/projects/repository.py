"""Queries over project tables. Every read takes a Scope and applies `visible_to`."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.pagination import decode_cursor, encode_cursor
from app.projects.models import (
    BaselineState,
    Milestone,
    MilestoneRevision,
    PlanBaseline,
    PlanBaselineItem,
    Project,
    ProjectMembership,
    ProjectStatus,
    ResearchDecision,
    Task,
)


async def get_project(session: AsyncSession, scope: Scope, project_id: UUID) -> Project | None:
    return (
        await session.execute(
            select(Project).where(Project.id == project_id, visible_to(scope, Project))
        )
    ).scalar_one_or_none()


async def list_projects(
    session: AsyncSession,
    scope: Scope,
    *,
    limit: int,
    cursor: str | None,
    status: ProjectStatus | None = None,
) -> tuple[list[Project], str | None]:
    statement = select(Project).where(visible_to(scope, Project)).order_by(Project.id)
    if status is not None:
        statement = statement.where(Project.status == status)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        statement = statement.where(Project.id > UUID(str(decoded["after"])))

    rows = list((await session.execute(statement.limit(limit + 1))).scalars().all())
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], encode_cursor({"after": str(rows[limit - 1].id)})


async def get_membership(
    session: AsyncSession, scope: Scope, membership_id: UUID
) -> ProjectMembership | None:
    return (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.id == membership_id, visible_to(scope, ProjectMembership)
            )
        )
    ).scalar_one_or_none()


async def list_memberships(
    session: AsyncSession, scope: Scope, project_id: UUID, *, include_past: bool
) -> list[ProjectMembership]:
    statement = (
        select(ProjectMembership)
        .where(ProjectMembership.project_id == project_id, visible_to(scope, ProjectMembership))
        .order_by(ProjectMembership.joined_on, ProjectMembership.id)
    )
    if not include_past:
        statement = statement.where(ProjectMembership.left_on.is_(None))
    return list((await session.execute(statement)).scalars().all())


async def active_membership(
    session: AsyncSession, project_id: UUID, student_id: UUID
) -> ProjectMembership | None:
    return (
        await session.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.student_id == student_id,
                ProjectMembership.left_on.is_(None),
            )
        )
    ).scalar_one_or_none()


async def memberships_active_in_range(
    session: AsyncSession, scope: Scope, *, local_start: date, local_end: date
) -> list[ProjectMembership]:
    """REP-01: memberships that overlap the week on a project that is currently active.

    `left_on` is exclusive, so a student who left on the Monday a period starts owes nothing for it.
    """
    return list(
        (
            await session.execute(
                select(ProjectMembership)
                .join(Project, Project.id == ProjectMembership.project_id)
                .where(
                    visible_to(scope, ProjectMembership),
                    Project.status == ProjectStatus.ACTIVE,
                    ProjectMembership.joined_on <= local_end,
                    or_(
                        ProjectMembership.left_on.is_(None),
                        ProjectMembership.left_on > local_start,
                    ),
                )
                .order_by(ProjectMembership.id)
            )
        )
        .scalars()
        .all()
    )


async def get_milestone(
    session: AsyncSession, scope: Scope, milestone_id: UUID
) -> Milestone | None:
    return (
        await session.execute(
            select(Milestone).where(Milestone.id == milestone_id, visible_to(scope, Milestone))
        )
    ).scalar_one_or_none()


async def list_milestones(session: AsyncSession, scope: Scope, project_id: UUID) -> list[Milestone]:
    return list(
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project_id, visible_to(scope, Milestone))
                .order_by(Milestone.target_on.nulls_last(), Milestone.id)
            )
        )
        .scalars()
        .all()
    )


async def list_milestone_revisions(
    session: AsyncSession, milestone_id: UUID
) -> list[MilestoneRevision]:
    return list(
        (
            await session.execute(
                select(MilestoneRevision)
                .where(MilestoneRevision.milestone_id == milestone_id)
                .order_by(MilestoneRevision.revision_no)
            )
        )
        .scalars()
        .all()
    )


async def get_task(session: AsyncSession, scope: Scope, task_id: UUID) -> Task | None:
    return (
        await session.execute(select(Task).where(Task.id == task_id, visible_to(scope, Task)))
    ).scalar_one_or_none()


async def list_tasks(
    session: AsyncSession, scope: Scope, project_id: UUID, *, milestone_id: UUID | None = None
) -> list[Task]:
    statement = (
        select(Task).where(Task.project_id == project_id, visible_to(scope, Task)).order_by(Task.id)
    )
    if milestone_id is not None:
        statement = statement.where(Task.milestone_id == milestone_id)
    return list((await session.execute(statement)).scalars().all())


async def list_decisions(
    session: AsyncSession, scope: Scope, project_id: UUID
) -> list[ResearchDecision]:
    return list(
        (
            await session.execute(
                select(ResearchDecision)
                .where(
                    ResearchDecision.project_id == project_id,
                    visible_to(scope, ResearchDecision),
                )
                .order_by(ResearchDecision.decided_on.desc(), ResearchDecision.id)
            )
        )
        .scalars()
        .all()
    )


async def milestone_progress(
    session: AsyncSession, scope: Scope, project_id: UUID, *, today: date
) -> tuple[int, float | None, int, int]:
    """PROJ-06: (count, weighted completion, completed, overdue) from weights and fractions."""
    row = (
        await session.execute(
            select(
                func.count(Milestone.id),
                func.sum(Milestone.weight * Milestone.accepted_completion),
                func.sum(Milestone.weight),
                func.count(Milestone.id).filter(Milestone.status == "completed"),
                func.count(Milestone.id).filter(
                    Milestone.target_on < today,
                    Milestone.status.not_in(("completed", "cancelled")),
                ),
            ).where(Milestone.project_id == project_id, visible_to(scope, Milestone))
        )
    ).one()
    count, weighted, total_weight, completed, overdue = row
    fraction = float(weighted) / float(total_weight) if total_weight else None
    return count, fraction, completed, overdue


async def count_open_blockers(session: AsyncSession, scope: Scope, project_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.project_id == project_id,
                visible_to(scope, Task),
                or_(Task.status == "blocked", Task.blocker.is_not(None)),
                Task.status.not_in(("done", "dropped")),
            )
        )
    ).scalar_one()


IN_EFFECT = (BaselineState.FROZEN, BaselineState.ACCEPTED)


async def baseline_in_effect(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> PlanBaseline | None:
    """ASSESS-05: only a frozen or accepted plan is a commitment to measure against."""
    return (
        await session.execute(
            select(PlanBaseline).where(
                PlanBaseline.membership_id == membership_id,
                PlanBaseline.period_id == period_id,
                PlanBaseline.state.in_(IN_EFFECT),
                visible_to(scope, PlanBaseline),
            )
        )
    ).scalar_one_or_none()


async def latest_baseline(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> PlanBaseline | None:
    return (
        await session.execute(
            select(PlanBaseline)
            .where(
                PlanBaseline.membership_id == membership_id,
                PlanBaseline.period_id == period_id,
                visible_to(scope, PlanBaseline),
            )
            .order_by(PlanBaseline.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_baseline(
    session: AsyncSession, scope: Scope, baseline_id: UUID
) -> PlanBaseline | None:
    return (
        await session.execute(
            select(PlanBaseline).where(
                PlanBaseline.id == baseline_id, visible_to(scope, PlanBaseline)
            )
        )
    ).scalar_one_or_none()


async def list_baselines(
    session: AsyncSession, scope: Scope, *, membership_id: UUID, period_id: UUID
) -> list[PlanBaseline]:
    return list(
        (
            await session.execute(
                select(PlanBaseline)
                .where(
                    PlanBaseline.membership_id == membership_id,
                    PlanBaseline.period_id == period_id,
                    visible_to(scope, PlanBaseline),
                )
                .order_by(PlanBaseline.version_no)
            )
        )
        .scalars()
        .all()
    )


async def baseline_items(session: AsyncSession, baseline_id: UUID) -> list[PlanBaselineItem]:
    return list(
        (
            await session.execute(
                select(PlanBaselineItem)
                .where(PlanBaselineItem.baseline_id == baseline_id)
                .order_by(PlanBaselineItem.position, PlanBaselineItem.id)
            )
        )
        .scalars()
        .all()
    )
