"""Queries over project tables. Every read takes a Scope and applies `visible_to`."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, visible_to
from app.core.pagination import cursor_after, encode_cursor
from app.identity.models import User
from app.projects.models import (
    BaselineState,
    MembershipOrigin,
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
    after = cursor_after(cursor)
    if after is not None:
        statement = statement.where(Project.id > after)

    rows = list((await session.execute(statement.limit(limit + 1))).scalars().all())
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], encode_cursor({"after": str(rows[limit - 1].id)})


def _joinable(scope: Scope) -> ColumnElement[bool]:
    """The projects a student may put themselves on (PROJ-07).

    Deliberately not `visible_to(scope, Project)`: the whole point is that the caller is not a
    member yet, so the ordinary policy would return nothing. This predicate is the one gate for
    both what a non-member may see and what they may join, so the two cannot drift apart.

    Pinned to `scope.workspace_id` rather than `Scope.within`: the membership this read exists to
    enable is written against a composite foreign key on the anchor workspace, so a project from
    anywhere else would fail in the database rather than be refused in words (ADR 0016). A student
    belongs to exactly one workspace anyway; naming the anchor says which one and why.
    """
    return and_(
        Project.workspace_id == scope.workspace_id,
        Project.status == ProjectStatus.ACTIVE,
        Project.open_to_join.is_(True),
        Project.id.notin_(scope.project_ids) if scope.project_ids else true(),
    )


async def joinable_project(session: AsyncSession, scope: Scope, project_id: UUID) -> Project | None:
    return (
        await session.execute(select(Project).where(Project.id == project_id, _joinable(scope)))
    ).scalar_one_or_none()


async def joinable_projects(
    session: AsyncSession, scope: Scope, *, limit: int
) -> list[tuple[Project, int]]:
    """Open projects with how many people are on each, so the choice is not made blind."""
    members = (
        select(func.count())
        .select_from(ProjectMembership)
        .where(
            ProjectMembership.project_id == Project.id,
            ProjectMembership.left_on.is_(None),
        )
        .correlate(Project)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Project, members)
        .where(_joinable(scope))
        .order_by(Project.title, Project.id)
        .limit(limit)
    )
    return [(project, count) for project, count in rows]


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


async def ended_membership_dates(
    session: AsyncSession, workspace_id: UUID, student_id: UUID
) -> dict[UUID, date]:
    """When this student left each project they are no longer on (PROJ-02 keeps the row).

    Keyed by project rather than by membership: a student who left and was later assigned again
    has two rows, and the one that matters to a reader is the open one — which is absent here,
    because an open membership has no `left_on` to report.
    """
    rows = await session.execute(
        select(ProjectMembership.project_id, ProjectMembership.left_on).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.student_id == student_id,
            ProjectMembership.left_on.is_not(None),
        )
    )
    return {project_id: left_on for project_id, left_on in rows}


async def list_memberships(
    session: AsyncSession, scope: Scope, project_id: UUID, *, include_past: bool
) -> list[tuple[ProjectMembership, str]]:
    """Each membership the caller may see, with the member's display name (PROJ-02)."""
    statement = (
        select(ProjectMembership, User.display_name)
        .join(User, User.id == ProjectMembership.student_id)
        .where(ProjectMembership.project_id == project_id, visible_to(scope, ProjectMembership))
        .order_by(ProjectMembership.joined_on, ProjectMembership.id)
    )
    if not include_past:
        statement = statement.where(ProjectMembership.left_on.is_(None))
    return [(row, name) for row, name in (await session.execute(statement))]


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


async def active_memberships_for_student(
    session: AsyncSession, workspace_id: UUID, student_id: UUID
) -> list[ProjectMembership]:
    """Every membership the student has not yet left, across all projects (ADR 0011).

    Unscoped: the caller is the `UserRemoved` handler, which runs inside the removing professor's
    transaction and must close every membership, not only those a Scope would surface.
    """
    return list(
        (
            await session.execute(
                select(ProjectMembership)
                .where(
                    ProjectMembership.workspace_id == workspace_id,
                    ProjectMembership.student_id == student_id,
                    ProjectMembership.left_on.is_(None),
                )
                .order_by(ProjectMembership.joined_on, ProjectMembership.id)
            )
        )
        .scalars()
        .all()
    )


async def memberships_open_through(
    session: AsyncSession, membership_ids: Collection[UUID], *, through: date
) -> set[UUID]:
    """Of these memberships, the ones not already ended by `through`. `left_on` is exclusive."""
    if not membership_ids:
        return set()
    rows = await session.execute(
        select(ProjectMembership.id).where(
            ProjectMembership.id.in_(list(membership_ids)),
            or_(ProjectMembership.left_on.is_(None), ProjectMembership.left_on > through),
        )
    )
    return set(rows.scalars().all())


async def memberships_active_in_range(
    session: AsyncSession, scope: Scope, *, local_start: date, local_end: date
) -> list[ProjectMembership]:
    """REP-01: memberships that overlap the week on a project that is currently active.

    `left_on` is exclusive and is compared against the *end* of the week: a report covers a week,
    so a membership that did not last the week does not owe one. A student who leaves on the
    Friday therefore owes nothing for that week, and neither does one who left the Monday before.

    That is a change from the earlier rule, which compared against the start and so kept the week
    in progress. It was defended on the grounds that leaving should not be a way to drop a report
    already owed; the answer taken here is that a project you are no longer on should not sit on
    your week at all, and that the professor and the student must agree about it either way.

    A membership acquired by joining an existing project owes only weeks that began after the
    student joined (PROJ-07). Joining on a Saturday would otherwise owe a report by Sunday 23:59,
    and if they had already submitted that week they would be counted missing and emailed about it
    — a late mark inflicted by the act of joining.

    Starting a project is the other way round: the student is announcing work they are already
    doing, so it owes the week it lands in, exactly as a professor's assignment does.
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
                        ProjectMembership.origin != MembershipOrigin.SELF_JOINED,
                        ProjectMembership.joined_on <= local_start,
                    ),
                    or_(
                        ProjectMembership.left_on.is_(None),
                        ProjectMembership.left_on > local_end,
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
