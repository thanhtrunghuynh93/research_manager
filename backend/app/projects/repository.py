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
    PlanBaseline,
    PlanBaselineItem,
    Project,
    ProjectMembership,
    ProjectStatus,
)


def open_on(day: date) -> ColumnElement[bool]:
    """The one meaning of "not yet ended" for a membership: `left_on` is absent or after `day`.

    `left_on` is exclusive — the first day the student is no longer a member — so a membership
    the professor has set to end next month is still in force today. Testing `left_on IS NULL`
    instead treated it as already over: a removed student kept the project, and a second,
    overlapping membership could be written beside it.

    Deliberately silent on `joined_on`. A membership that starts later is not ended either: it
    still conflicts with a second enrolment and is still closed when the student is removed. The
    reads that ask whether a membership is *in effect* on a day add the start, via `in_effect_on`.
    """
    return or_(ProjectMembership.left_on.is_(None), ProjectMembership.left_on > day)


def in_effect_on(day: date) -> ColumnElement[bool]:
    """A membership that has begun and not yet ended on `day` — what grants access (AUTH-03)."""
    return and_(ProjectMembership.joined_on <= day, open_on(day))


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

    Pinned to `scope.workspace_id`: the membership this read exists to enable is written against a
    composite foreign key on that workspace.
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
    session: AsyncSession, scope: Scope, *, limit: int, today: date
) -> list[tuple[Project, int]]:
    """Open projects with how many people are on each, so the choice is not made blind."""
    members = (
        select(func.count())
        .select_from(ProjectMembership)
        .where(
            ProjectMembership.project_id == Project.id,
            open_on(today),
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
    session: AsyncSession, workspace_id: UUID, student_id: UUID, *, today: date
) -> dict[UUID, date]:
    """When this student left each project they are no longer on (PROJ-02 keeps the row).

    Keyed by project rather than by membership: a student who left and was later assigned again
    has two rows, and the one that matters to a reader is the open one — which is absent here,
    because an open membership has no `left_on` to report. A `left_on` still in the future is not
    an ending yet, so it is not reported either (`open_on`).
    """
    rows = await session.execute(
        select(ProjectMembership.project_id, ProjectMembership.left_on).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.student_id == student_id,
            ~open_on(today),
        )
    )
    return {project_id: left_on for project_id, left_on in rows}


async def list_memberships(
    session: AsyncSession, scope: Scope, project_id: UUID, *, include_past: bool, today: date
) -> list[tuple[ProjectMembership, str]]:
    """Each membership the caller may see, with the member's display name (PROJ-02)."""
    statement = (
        select(ProjectMembership, User.display_name)
        .join(User, User.id == ProjectMembership.student_id)
        .where(ProjectMembership.project_id == project_id, visible_to(scope, ProjectMembership))
        .order_by(ProjectMembership.joined_on, ProjectMembership.id)
    )
    if not include_past:
        statement = statement.where(open_on(today))
    return [(row, name) for row, name in (await session.execute(statement))]


async def active_membership(
    session: AsyncSession, project_id: UUID, student_id: UUID, *, on: date
) -> ProjectMembership | None:
    """The student's membership on this project still open on `on`, including one not yet begun.

    `_enrol` passes the new membership's start, so a row overlapping it is found and one that
    ends first is not: rejoining after a dated ending is allowed, rejoining into it is not. Of
    two open rows the earlier is returned, being the one in force or the next to begin.
    """
    return (
        await session.execute(
            select(ProjectMembership)
            .where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.student_id == student_id,
                open_on(on),
            )
            .order_by(ProjectMembership.joined_on, ProjectMembership.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def active_memberships_for_student(
    session: AsyncSession, workspace_id: UUID, student_id: UUID, *, today: date
) -> list[ProjectMembership]:
    """Every membership the student has not yet left, across all projects (ADR 0011).

    Including one set to end later and one not yet begun: removal ends both today.

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
                    open_on(today),
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
    """Of these memberships, the ones that still owe a week ending on `through`.

    Two tests, and they are the two `memberships_active_in_range` derives by: the membership was
    not already ended (`left_on` is exclusive), and the project is still `ACTIVE`.

    The project status half was missing, and its absence was visible from the professor's side of
    the product: completing a project stopped *new* obligations deriving and left the ones already
    derived sitting on the current week, so the student still owed a report for work the professor
    had just called done — and was emailed about it at 00:00 on the meeting day (REP-08). An
    obligation already derived has to be judged by the rule that would derive it today, which is
    what the docstring on `memberships_still_owing` already claimed.

    It covers pausing and archiving for the same reason. A paused project is the case REP-06 names
    outright — leave, holidays, a project on hold — and none of them owe a week.
    """
    if not membership_ids:
        return set()
    rows = await session.execute(
        select(ProjectMembership.id)
        .join(Project, Project.id == ProjectMembership.project_id)
        .where(
            ProjectMembership.id.in_(list(membership_ids)),
            open_on(through),
            Project.status == ProjectStatus.ACTIVE,
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
    — a late mark inflicted by the act of joining. "After" is strict: a join on the Monday the week
    begins owes from the next Monday, as PROJ-02 and the joinable list both promise.

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
                    in_effect_on(local_end),
                    or_(
                        ProjectMembership.origin != MembershipOrigin.SELF_JOINED,
                        ProjectMembership.joined_on < local_start,
                    ),
                )
                .order_by(ProjectMembership.id)
            )
        )
        .scalars()
        .all()
    )


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


async def titles(session: AsyncSession, project_ids: Collection[UUID]) -> dict[UUID, str]:
    """Each project's title by id. Unscoped, like `project_title`: a name and nothing else."""
    if not project_ids:
        return {}
    rows = await session.execute(
        select(Project.id, Project.title).where(Project.id.in_(list(project_ids)))
    )
    return {project_id: title for project_id, title in rows}
