"""Turning a question into a plan (QA-05, architecture §11).

Two jobs. The model proposes which facts to compute and what to search for; this module then
*resolves* what it proposed against the database. That order matters: a model asked about "Minh"
may produce a plausible id, and a plan that reached a record because a name looked right would be
the whole authorization model defeated by autocomplete.

Relative time is resolved here rather than by the model, because "last month" has an exact answer
and a language model is the wrong instrument for arithmetic on dates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway, Budget, CallContext
from app.ai.schemas import RoutePlan
from app.assistant import facts
from app.core.authz import Scope
from app.identity import service as identity_service
from app.projects import service as projects_service

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

# Recognised without a model call: these have exact answers and never need a guess.
_RELATIVE = {
    "today": timedelta(days=1),
    "this week": timedelta(days=7),
    "last week": timedelta(days=14),
    "this month": timedelta(days=30),
    "last month": timedelta(days=60),
    "last six weeks": timedelta(weeks=6),
    "last 6 weeks": timedelta(weeks=6),
    "this term": timedelta(days=180),
    "this semester": timedelta(days=180),
}

# A question that is plainly about a count, a date, or a list, so the fact route is taken even if
# the model is unavailable. Each maps to a registered function name.
_KEYWORD_FACTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmissing\b.*\breports?\b|\breports?\b.*\bmissing\b", re.I), "missing_reports"),
    (re.compile(r"\b(next|upcoming)\b.*\bdeadline\b|\bwhen\b.*\bdue\b", re.I), "next_deadline"),
    (re.compile(r"\blate\b|\bon time\b|\btiming\b", re.I), "timing_counts"),
    (re.compile(r"\bwho\b.*\b(on|in)\b.*\bproject\b|\bmembers?\b", re.I), "members"),
    (
        re.compile(r"\breview\b.*\bqueue\b|\bwaiting\b.*\breview\b|\bto review\b", re.I),
        "review_queue",
    ),
    (
        re.compile(r"\bstale\b|\bnot synced\b|\bsync(ed|ing)? (failed|issues?)\b", re.I),
        "stale_repositories",
    ),
    (re.compile(r"\bblock(ed|ing|ers?)\b|\bstuck\b", re.I), "blockers"),
    (
        re.compile(r"\bprogress(ed)?\b.*\b(over|last|weeks?)\b|\btrajector|\btrend", re.I),
        "progress_series",
    ),
]


@dataclass(slots=True)
class Plan:
    """A resolved plan: every id in it came from the database, not from the model."""

    intent: str
    fact_functions: list[str] = field(default_factory=list)
    search_query: str = ""
    student_id: UUID | None = None
    student_name: str = ""
    project_id: UUID | None = None
    project_name: str = ""
    since: datetime | None = None
    until: datetime | None = None
    as_of: datetime | None = None
    clarifying_question: str = ""
    prompt_version: str = ""
    model_name: str = ""
    notes: list[str] = field(default_factory=list)


async def plan_question(
    session: AsyncSession,
    scope: Scope,
    *,
    question: str,
    gateway: AIGateway,
    as_of: datetime,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Plan:
    """Ask the model for a plan, then keep only the parts the database confirms."""
    plan = Plan(
        intent="mixed",
        as_of=as_of,
        since=since or _relative_since(question, as_of),
        until=until,
        student_id=student_id,
        project_id=project_id,
    )

    result = await gateway.complete_structured(
        prompt_id="route_question",
        inputs={
            "fact_functions": facts.available(),
            "scope": _scope_summary(scope, plan),
            "question": question,
        },
        schema=RoutePlan,
        budget=Budget(max_tokens=512),
        context=CallContext(
            prompt_id="route_question",
            prompt_version=PROMPT_VERSION,
            workspace_id=scope.workspace_id,
            session=session,
            project_id=project_id,
        ),
    )
    plan.model_name = result.model
    plan.prompt_version = result.prompt_version

    if not result.ok:
        # The router failing must not take the answer with it: the keyword route still computes the
        # facts a question plainly asks for, and retrieval still runs.
        plan.notes.append("the routing step did not complete; falling back to keyword routing")
        plan.fact_functions = _keyword_facts(question)
        plan.search_query = question
        plan.intent = "fact" if plan.fact_functions and not _looks_narrative(question) else "mixed"
        await _resolve_entities(session, scope, plan, [], [])
        return plan

    proposal = result.value
    assert proposal is not None  # result.ok was checked above
    plan.intent = proposal.intent
    plan.search_query = proposal.search_query or question
    plan.clarifying_question = proposal.clarifying_question

    # Only registered names survive. An invented one answers a different question (QA-02).
    named = [name for name in proposal.fact_functions if facts.get(name) is not None]
    dropped = sorted(set(proposal.fact_functions) - set(named))
    if dropped:
        plan.notes.append(f"ignored unknown fact function(s): {', '.join(dropped)}")
    plan.fact_functions = named or _keyword_facts(question)

    plan.since = plan.since or _parse(proposal.since)
    plan.until = plan.until or _parse(proposal.until)
    explicit_as_of = _parse(proposal.as_of)
    if explicit_as_of is not None and explicit_as_of < as_of:
        # QA-04: a historical question uses only what existed then.
        plan.as_of = explicit_as_of

    await _resolve_entities(session, scope, plan, proposal.student_names, proposal.project_names)
    if plan.clarifying_question:
        plan.intent = "clarify"
    return plan


async def _resolve_entities(
    session: AsyncSession,
    scope: Scope,
    plan: Plan,
    student_names: list[str],
    project_names: list[str],
) -> None:
    """Match names to records the caller may already see, and ask when the match is ambiguous."""
    if plan.student_id is None and student_names:
        matches = await _match_students(session, scope, student_names[0])
        if len(matches) == 1:
            plan.student_id, plan.student_name = matches[0]
        elif len(matches) > 1:
            plan.clarifying_question = (
                f"Which {student_names[0]} do you mean — "
                + ", ".join(name for _id, name in matches)
                + "?"
            )
        else:
            plan.notes.append(f"no student in this workspace matches {student_names[0]!r}")

    if plan.project_id is None and project_names:
        matches = await _match_projects(session, scope, project_names[0])
        if len(matches) == 1:
            plan.project_id, plan.project_name = matches[0]
        elif len(matches) > 1:
            plan.clarifying_question = (
                "Which project do you mean — " + ", ".join(name for _id, name in matches) + "?"
            )
        else:
            plan.notes.append(f"no project in this workspace matches {project_names[0]!r}")

    if plan.student_id is not None and not plan.student_name:
        plan.student_name = (
            await identity_service.get_user(session, scope, plan.student_id)
        ).display_name
    if plan.project_id is not None and not plan.project_name:
        plan.project_name = (
            await projects_service.get_project(session, scope, plan.project_id)
        ).title


async def _match_students(session: AsyncSession, scope: Scope, name: str) -> list[tuple[UUID, str]]:
    """Matched against users the caller may already see, so resolution leaks nothing (AUTH-02)."""
    needle = name.strip().lower()
    page = await identity_service.list_users(session, scope, limit=200)
    matches = [
        (user.id, user.display_name)
        for user in page.items
        if needle in user.display_name.lower() or needle in user.email.lower()
    ]
    exact = [row for row in matches if row[1].lower() == needle]
    return exact or matches


async def _match_projects(session: AsyncSession, scope: Scope, name: str) -> list[tuple[UUID, str]]:
    needle = name.strip().lower()
    page = await projects_service.list_projects(session, scope, limit=200)
    matches = [
        (project.id, project.title) for project in page.items if needle in project.title.lower()
    ]
    exact = [row for row in matches if row[1].lower() == needle]
    return exact or matches


def _keyword_facts(question: str) -> list[str]:
    return [name for pattern, name in _KEYWORD_FACTS if pattern.search(question)]


def _looks_narrative(question: str) -> bool:
    return bool(re.search(r"\bwhy\b|\bexplain\b|\bhow did\b|\bsummar", question, re.I))


def _relative_since(question: str, as_of: datetime) -> datetime | None:
    lowered = question.lower()
    for phrase, window in sorted(_RELATIVE.items(), key=lambda item: -len(item[0])):
        if phrase in lowered:
            return as_of - window
    return None


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        log.debug("the router proposed an unparseable date: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _scope_summary(scope: Scope, plan: Plan) -> dict[str, object]:
    return {
        "role": scope.role.value,
        "student_id": str(plan.student_id) if plan.student_id else None,
        "project_id": str(plan.project_id) if plan.project_id else None,
        "since": plan.since.isoformat() if plan.since else None,
        "until": plan.until.isoformat() if plan.until else None,
        "as_of": plan.as_of.isoformat() if plan.as_of else None,
    }
