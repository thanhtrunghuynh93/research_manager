"""The demo dataset (docs/repo_layout.md §6, `make seed`).

A workspace that looks like a term in progress: a professor, six students, four projects at
different research stages, eight weeks of periods, submitted reports, a connected repository with
commits and a pull request, and drafts waiting to be reviewed. It exists so the screens can be
opened, the end-to-end tests have something to act on, and a new contributor can see the product
rather than an empty shell.

Two things it deliberately includes because they are where the product's judgement shows: a week
with no repository evidence at all, and a week whose report claims more than the evidence supports.
A demo that only contains the happy path teaches the wrong thing about what this system does.

Everything goes through the ordinary services, so the seed cannot create a state the application
could not, and it is idempotent on the professor's address: running it twice is refused rather than
producing a second workspace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service as assessment_service
from app.core.db import run_in_session
from app.core.errors import ConflictError
from app.core.types import Role, Visibility
from app.evidence import service as evidence_service
from app.evidence.connectors.base import Actor, CommitMeta, PullRequest
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.evidence.models import EvidenceSourceKind
from app.identity import service as identity_service
from app.identity.models import User
from app.projects import service as projects_service
from app.projects.schemas import ResearchStage
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)

cli = typer.Typer(no_args_is_help=True, help="Load datasets for development and demos")


class AlreadySeededError(ConflictError):
    """This database already holds the demo dataset.

    A subclass rather than a flag so `load_demo` keeps its documented contract — a second run is
    refused, not duplicated — while the command line can tell the one refusal it expects apart
    from a conflict that means something is actually wrong.
    """

    title = "Demo dataset already loaded"


PASSWORD = "demo-password-change-me"  # noqa: S105 - a development dataset, never a deployment
PROF_EMAIL = "prof@example.edu"
FIRST_MONDAY = date(2026, 9, 14)
WEEKS = 8

STUDENTS = [
    ("an.nguyen@example.edu", "An Nguyen"),
    ("bao.tran@example.edu", "Bao Tran"),
    ("chi.le@example.edu", "Chi Le"),
    ("dung.pham@example.edu", "Dung Pham"),
    ("emma.olsen@example.edu", "Emma Olsen"),
    ("farid.haddad@example.edu", "Farid Haddad"),
]

PROJECTS: list[tuple[str, ResearchStage, str]] = [
    (
        "Retrieval baselines",
        ResearchStage.IMPLEMENTATION,
        "Reproduce and extend the retrieval baselines.",
    ),
    (
        "Calibration under drift",
        ResearchStage.THEORY,
        "Which coverage guarantees survive temporal drift.",
    ),
    (
        "Vietnamese corpus preparation",
        ResearchStage.DATA_PREPARATION,
        "Clean and normalise the corpus.",
    ),
    (
        "Survey of uncertainty estimates",
        ResearchStage.LITERATURE_REVIEW,
        "Classify post-hoc calibration work.",
    ),
]


@dataclass(frozen=True, slots=True)
class Seeded:
    workspace_id: UUID
    professor_id: UUID
    student_ids: list[UUID]
    project_ids: list[UUID]
    period_ids: list[UUID]
    reports: int
    assessments: int


@cli.command("demo")
def demo() -> None:
    """Load the demo dataset. Loading it a second time leaves the existing one alone."""
    try:
        result = run_in_session(load_demo)
    except AlreadySeededError:
        # The documented way to start is `scripts/run_mock.sh --seed`, so this runs whenever
        # anyone restarts against a volume that already has the data — the ordinary case, not a
        # fault. It used to escape as a traceback, and because run.sh runs under `set -e` that
        # aborted the whole startup: no ready banner, no frontend, just a stack trace.
        typer.echo("The demo dataset is already loaded; leaving it as it is.")
        typer.echo(f"  sign in as {PROF_EMAIL} with the password {PASSWORD!r}")
        return
    typer.echo(f"workspace {result.workspace_id}")
    typer.echo(f"  {len(result.student_ids)} students, {len(result.project_ids)} projects")
    typer.echo(f"  {len(result.period_ids)} reporting periods, {result.reports} reports submitted")
    typer.echo(f"  {result.assessments} draft assessments waiting for review")
    typer.echo(f"  sign in as {PROF_EMAIL} with the password {PASSWORD!r}")


async def load_demo(session: AsyncSession) -> Seeded:
    prof_scope, professor = await _workspace(session)
    students = await _students(session, prof_scope)
    projects = await _projects(session, prof_scope)
    await _memberships(session, prof_scope, students, projects)
    periods = await _calendar(session, prof_scope)
    await _repository(session, prof_scope, students, projects)
    reports = await _reports(session, students, projects, periods)
    assessments = await _assessments(session, prof_scope, students, projects, periods)

    return Seeded(
        workspace_id=prof_scope.workspace_id,
        professor_id=professor.id,
        student_ids=[student.id for student in students],
        project_ids=[project.id for project in projects],
        period_ids=[period.id for period in periods],
        reports=reports,
        assessments=assessments,
    )


async def _workspace(session: AsyncSession) -> tuple[Any, User]:
    try:
        bootstrapped = await identity_service.bootstrap_workspace(
            session,
            name="Demo Research Lab",
            prof_email=PROF_EMAIL,
            prof_display_name="Professor Demo",
        )
    except ConflictError as conflict:
        # bootstrap_workspace conflicts for exactly one reason: the professor's address is taken,
        # which here means the dataset is already in this database.
        raise AlreadySeededError(
            f"the demo dataset is already loaded ({PROF_EMAIL} exists)"
        ) from conflict
    await identity_service.accept_invitation(session, token=bootstrapped.token, password=PASSWORD)
    professor = await session.get(User, bootstrapped.user.id)
    assert professor is not None
    return await identity_service.scope_for(session, professor), professor


async def _students(session: AsyncSession, prof_scope: Any) -> list[User]:
    students = []
    for email, name in STUDENTS:
        invited = await identity_service.invite_user(
            session, prof_scope, email=email, display_name=name, role=Role.STUDENT
        )
        accepted = await identity_service.accept_invitation(
            session, token=invited.token, password=PASSWORD
        )
        user = await session.get(User, accepted.id)
        assert user is not None
        students.append(user)
    return students


async def _projects(session: AsyncSession, prof_scope: Any) -> list[Any]:
    projects = []
    for title, stage, description in PROJECTS:
        project = await projects_service.create_project(
            session, prof_scope, title=title, stage=stage, description=description
        )
        await projects_service.update_project(session, prof_scope, project.id, status="active")
        projects.append(project)

    # One project stands open, so the joinable list demonstrates something rather than an empty
    # panel (PROJ-07). The rest stay closed, which is the default and the safer half of the rule.
    await projects_service.update_project(session, prof_scope, projects[-1].id, open_to_join=True)

    # A dated decision, so the project workspace has something real to show (PROJ-01).
    await projects_service.record_decision(
        session,
        prof_scope,
        projects[0].id,
        decision="Freeze the evaluation split at the September snapshot.",
        rationale="Comparability across the term matters more than a slightly larger test set.",
        decided_on=FIRST_MONDAY + timedelta(days=2),
    )
    return projects


async def _memberships(
    session: AsyncSession, prof_scope: Any, students: list[User], projects: list[Any]
) -> None:
    # Two students share the first project so joint attribution has something to resolve (AC-06),
    # and one student is on two projects so a weekly package has two entries (AC-01).
    assignments = [
        (students[0], projects[0], "baselines and evaluation"),
        (students[1], projects[0], "data loader and infrastructure"),
        (students[0], projects[1], "coverage proofs"),
        (students[2], projects[2], "normalisation"),
        (students[3], projects[2], "deduplication"),
        (students[4], projects[3], "survey and synthesis"),
        (students[5], projects[1], "drift experiments"),
    ]
    for student, project, responsibility in assignments:
        await projects_service.add_member(
            session,
            prof_scope,
            project.id,
            student_id=student.id,
            responsibility=responsibility,
            joined_on=FIRST_MONDAY - timedelta(days=14),
        )


async def _calendar(session: AsyncSession, prof_scope: Any) -> list[Any]:
    await reporting_service.configure_calendar(
        session,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=FIRST_MONDAY,
    )
    periods = await reporting_service.ensure_periods(
        session, prof_scope, through=FIRST_MONDAY + timedelta(weeks=WEEKS)
    )
    for period in periods:
        await reporting_service.ensure_obligations(session, prof_scope, period.id)

    # One approved exception, so the missing-report logic has a case to get right (AC-08).
    if len(periods) > 1:
        obligations = await reporting_service.list_obligations(session, prof_scope, periods[1].id)
        if obligations:
            await reporting_service.excuse_obligation(
                session, prof_scope, obligations[-1].id, reason="Approved conference leave"
            )
    return periods


async def _repository(
    session: AsyncSession, prof_scope: Any, students: list[User], projects: list[Any]
) -> None:
    """A connected repository on the fake connector: no credential, no network, real events."""
    at = datetime.combine(FIRST_MONDAY, datetime.min.time(), tzinfo=UTC) + timedelta(days=2)
    connector = FakeRepositoryConnector(
        commits=[
            CommitMeta(
                sha="a1f3c9e",
                message="loader: read the judgment file with 1-based query ids",
                authored_at=at,
                committed_at=at,
                actors=[Actor(role="author", login="an-nguyen", email=STUDENTS[0][0])],
                paths=["data/loader.py", "tests/test_loader.py"],
                additions=52,
                deletions=6,
                files_changed=2,
            ),
            CommitMeta(
                sha="3d9f001",
                message="metrics: nDCG, MRR, recall with per-query output",
                authored_at=at + timedelta(days=1),
                committed_at=at + timedelta(days=1),
                actors=[
                    Actor(role="author", login="an-nguyen", email=STUDENTS[0][0]),
                    Actor(role="author", login="bao-tran", email=STUDENTS[1][0]),
                ],
                paths=["eval/metrics.py"],
                additions=140,
                deletions=0,
                files_changed=1,
            ),
        ],
        pull_requests=[
            PullRequest(
                number=212,
                title="evaluation pipeline",
                state="merged",
                created_at=at,
                updated_at=at + timedelta(days=2),
                merged_at=at + timedelta(days=2),
                merge_commit_sha="3d9f001",
                actors=[
                    Actor(role="author", login="an-nguyen"),
                    # REPO-03: merging is its own role and never transfers authorship (AC-06).
                    Actor(role="merger", login="bao-tran"),
                ],
            )
        ],
    )
    repository = await evidence_service.connect_repository(
        session,
        prof_scope,
        provider="github",
        external_id="demo-1",
        full_name="demo-lab/retrieval",
        connector=connector,
    )
    await evidence_service.link_project(
        session, prof_scope, repository.id, project_id=projects[0].id
    )
    for student, login in ((students[0], "an-nguyen"), (students[1], "bao-tran")):
        await evidence_service.map_identity(
            session, prof_scope, student_id=student.id, provider="github", login=login
        )
    await evidence_service.sync_repository(session, prof_scope, repository.id, connector=connector)
    await evidence_service.resolve_contributions(session, repository.id)

    await evidence_service.index_evidence(
        session,
        workspace_id=prof_scope.workspace_id,
        source_kind=EvidenceSourceKind.DECISION,
        source_id=projects[0].id,
        source_version="1",
        text="Project decision: the evaluation split is frozen at the September snapshot.",
        visibility=Visibility.PROJECT_SHARED,
        locator=f"/projects/{projects[0].id}#decisions",
        project_id=projects[0].id,
        source_time=at,
    )


ENTRIES: dict[int, dict[str, str]] = {
    0: {
        "work_performed": "Implemented the corpus loader and wired the BM25 baseline through the "
        "shared evaluation harness. Fixed an off-by-one in the judgment parser.",
        "results": "BM25 reaches nDCG@10 = 0.412; the dense baseline reaches 0.438. The gap is "
        "smaller than the published one, which the shorter documents in our corpus explain.",
        "deviations": "",
    },
    1: {
        "work_performed": "Tested whether curriculum ordering improves convergence. Three "
        "orderings, five seeds each.",
        "results": "It does not help: the three orderings sit inside the seed spread. The "
        "difficulty proxy correlates with length at r = 0.82, so two of the curricula were nearly "
        "the same experiment. That is the finding, and it invalidates the proposal's design.",
        "deviations": "Dropping this line rather than tuning it further.",
    },
    2: {
        # A week whose claim outruns its evidence: the assessment should say so (AC-07).
        "work_performed": "Ran the full sweep on the private cluster.",
        "results": "We beat the published state of the art by four points.",
        "deviations": "The cluster queue has been full since Tuesday, so nothing is in the "
        "repository yet.",
    },
}


async def _reports(
    session: AsyncSession, students: list[User], projects: list[Any], periods: list[Any]
) -> int:
    """Three submitted weeks for the first student, one each for the rest."""
    submitted = 0
    first = students[0]
    scope = await identity_service.scope_for(session, first)
    for index, period in enumerate(periods[:3]):
        await reporting_service.submit_report(
            session,
            scope,
            period_id=period.id,
            entries=[
                {
                    "project_id": projects[0].id,
                    "stage": "implementation",
                    **ENTRIES[index],
                    "next_plan": {
                        "items": [
                            {"planned_outcome": "Run the hybrid fusion baseline", "weight": 1}
                        ]
                    },
                },
                {
                    "project_id": projects[1].id,
                    "stage": "theory",
                    "work_performed": "Proved the projected bound under convexity.",
                    "results": "Theorem 3.1 holds with the hypothesis added; the constant is twice "
                    "the unprojected one, correcting the earlier draft.",
                },
            ],
        )
        submitted += 1

    for student, project, stage in (
        (students[1], projects[0], "implementation"),
        (students[2], projects[2], "data_preparation"),
        (students[4], projects[3], "literature_review"),
    ):
        student_scope = await identity_service.scope_for(session, student)
        await reporting_service.submit_report(
            session,
            student_scope,
            period_id=periods[0].id,
            entries=[
                {
                    "project_id": project.id,
                    "stage": stage,
                    "work_performed": f"{student.display_name} worked on {project.title}.",
                    "results": "Recorded in the entry; see the attached evidence.",
                }
            ],
        )
        submitted += 1
    return submitted


async def _assessments(
    session: AsyncSession,
    prof_scope: Any,
    students: list[User],
    projects: list[Any],
    periods: list[Any],
) -> int:
    """Drafts on the fake gateway, and one approved week so a student has released feedback."""
    gateway = FakeGateway()
    produced = 0
    for index, period in enumerate(periods[:3]):
        assessment = await assessment_service.run_pipeline(
            session,
            student_id=students[0].id,
            project_id=projects[0].id,
            period_id=period.id,
            gateway=gateway,
        )
        if assessment is None:
            continue
        produced += 1
        if index == 0:
            await assessment_service.approve(session, prof_scope, assessment.id)

    await assessment_service.add_supervision_note(
        session,
        prof_scope,
        body="Private: pace looks fine, but check the cluster access before the next review.",
        student_id=students[0].id,
        project_id=projects[0].id,
    )
    return produced


# ------------------------------------------------------------------ the AC-19 drill


@dataclass(frozen=True, slots=True)
class DeadlineDrill:
    period_id: UUID
    unsubmitted_email: str
    submitted_email: str
    excused_email: str
    notifications: int
    emails_sent: int


@cli.command("missed-deadline-drill")
def missed_deadline_drill() -> None:
    """Set up and run AC-19 against the real mail path, for the end-to-end test.

    The product has no screen for "make this deadline have passed", which is the one precondition
    the browser cannot create. Everything after that — reading obligations at send time, writing
    the notifications, draining the email queue through SMTP — is the production path, not a
    simulation of it.
    """
    result = run_in_session(run_deadline_drill)
    typer.echo(
        json_line(
            {
                "period_id": str(result.period_id),
                "unsubmitted_email": result.unsubmitted_email,
                "submitted_email": result.submitted_email,
                "excused_email": result.excused_email,
                "notifications": result.notifications,
                "emails_sent": result.emails_sent,
            }
        )
    )


def json_line(payload: dict[str, Any]) -> str:
    import orjson

    return orjson.dumps(payload).decode()


async def run_deadline_drill(session: AsyncSession, *, sender: Any | None = None) -> DeadlineDrill:
    """AC-19: one unsubmitted student, one who submitted at 23:58, one on approved leave."""
    from app.notifications import service as notifications_service
    from app.notifications.scheduler_tasks import email_sender
    from app.reporting.models import ReportingPeriod

    professor = await _require_professor(session)
    prof_scope = await identity_service.scope_for(session, professor)
    students = await _drill_students(session, prof_scope)
    project = await projects_service.create_project(
        session,
        prof_scope,
        title=f"Deadline drill {datetime.now(UTC):%H%M%S}",
        stage=ResearchStage.IMPLEMENTATION,
    )
    await projects_service.update_project(session, prof_scope, project.id, status="active")

    # A week of its own, past the end of the demo calendar, so the only obligations in it belong
    # to the three students this drill just created. Sharing a week with the demo's students would
    # make "who received mail" a question about the fixture rather than about the rule.
    existing = await reporting_service.list_periods(session, prof_scope)
    horizon = max((row.local_end for row in existing), default=FIRST_MONDAY)
    fresh = await reporting_service.ensure_periods(
        session, prof_scope, through=horizon + timedelta(days=7)
    )
    period = fresh[0] if fresh else existing[-1]

    for student in students:
        await projects_service.add_member(
            session,
            prof_scope,
            project.id,
            student_id=student.id,
            joined_on=period.local_start,
        )
    await reporting_service.ensure_obligations(session, prof_scope, period.id)

    # The one precondition no screen can create: a deadline already behind us.
    row = await session.get(ReportingPeriod, period.id)
    assert row is not None
    row.deadline_utc = datetime.now(UTC) - timedelta(minutes=5)
    row.reminder_due_utc = datetime.now(UTC) - timedelta(minutes=4)
    row.reminder_dispatched_at = None
    await session.flush()

    submitted_scope = await identity_service.scope_for(session, students[1])
    await reporting_service.submit_report(
        session,
        submitted_scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Submitted with two minutes to spare.",
                "results": "Recorded in the entry.",
            }
        ],
    )
    for obligation in await reporting_service.list_obligations(
        session, prof_scope, period.id, student_id=students[2].id
    ):
        await reporting_service.excuse_obligation(
            session, prof_scope, obligation.id, reason="Approved leave"
        )

    # From here on it is the production path.
    notifications = await notifications_service.dispatch_missed_deadline(
        session, period.id, at=datetime.now(UTC)
    )
    sent = await notifications_service.send_queued_emails(
        session,
        sender or email_sender(),  # type: ignore[arg-type]
    )

    return DeadlineDrill(
        period_id=period.id,
        unsubmitted_email=students[0].email,
        submitted_email=students[1].email,
        excused_email=students[2].email,
        notifications=len(notifications) if isinstance(notifications, list) else 0,
        emails_sent=sent,
    )


async def _require_professor(session: AsyncSession) -> User:
    from sqlalchemy import select

    professor = (
        await session.execute(select(User).where(User.email == PROF_EMAIL))
    ).scalar_one_or_none()
    if professor is None:
        raise RuntimeError("load the demo dataset first: python -m app.cli seed demo")
    return professor


async def _drill_students(session: AsyncSession, prof_scope: Any) -> list[User]:
    from sqlalchemy import select

    stamp = f"{datetime.now(UTC):%H%M%S}"
    students = []
    for role in ("unsubmitted", "submitted", "excused"):
        email = f"drill-{role}-{stamp}@example.edu"
        invited = await identity_service.invite_user(
            session, prof_scope, email=email, display_name=f"Drill {role}", role=Role.STUDENT
        )
        accepted = await identity_service.accept_invitation(
            session, token=invited.token, password=PASSWORD
        )
        user = (await session.execute(select(User).where(User.id == accepted.id))).scalar_one()
        students.append(user)
    return students
