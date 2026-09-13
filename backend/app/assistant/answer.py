"""Building an answer, and refusing to let it claim more than it can (QA-03, QA-04, AC-07).

Three rules shape this module.

A computed fact is never regenerated. If the obligations table says three reports are missing, the
answer says three, and the model is not given the opportunity to round it. Facts are rendered
straight into the answer text; the model contributes synthesis *around* them.

Every citation is checked against what was actually retrieved before the answer is returned. A
citation the model invented is dropped and the fact of the drop is recorded in `gaps`, because an
answer quietly missing its support reads exactly like a well-supported one.

Nothing here can act. Suggestions are text. Approving, sending, and changing are endpoints a person
uses (QA-07).
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway, Budget, CallContext, Result
from app.ai.schemas import AnswerDraft
from app.assistant.facts import Fact
from app.assistant.retrieval import Passage
from app.assistant.schemas import AnswerScope, CitationOut, FactOut
from app.core import metrics
from app.core.authz import Scope

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
MAX_EVIDENCE_CHARS = 4000


async def draft(
    session: AsyncSession,
    scope: Scope,
    *,
    gateway: AIGateway,
    question: str,
    answer_scope: AnswerScope,
    computed: list[Fact],
    passages: list[Passage],
) -> Result[AnswerDraft]:
    return await gateway.complete_structured(
        prompt_id="answer",
        inputs={
            "scope": answer_scope.model_dump(mode="json"),
            "question": question,
            "facts": [_fact_payload(fact) for fact in computed],
            "evidence": [_passage_payload(passage) for passage in passages],
        },
        schema=AnswerDraft,
        budget=Budget(max_tokens=2048),
        context=CallContext(
            prompt_id="answer",
            prompt_version=PROMPT_VERSION,
            workspace_id=scope.workspace_id,
            session=session,
            project_id=answer_scope.project_id,
        ),
    )


def render_facts_only(computed: list[Fact]) -> str:
    """The answer to a pure fact question, written by arithmetic rather than by a model (AC-15).

    Deliberately plain. The professor asked how many reports are missing; the answer is the number,
    the instant it was true, and the rule that produced it.
    """
    if not computed:
        return "Nothing in the records answers that question."
    lines = []
    for fact in computed:
        lines.append(fact.render())
        if fact.note:
            lines.append(f"  {fact.note}")
    return "\n".join(lines)


def validate_citations(
    draft_value: AnswerDraft, passages: list[Passage], computed: list[Fact]
) -> tuple[list[CitationOut], list[str]]:
    """Keep only citations that point at something actually retrieved, and say what was dropped."""
    by_id = {passage.citation_id: passage for passage in passages}
    kept: dict[str, CitationOut] = {}
    gaps: list[str] = []

    cited = list(draft_value.cited_evidence_ref_ids)
    for section in draft_value.synthesis:
        cited.extend(section.evidence_ref_ids)

    invented = 0
    for reference in cited:
        passage = by_id.get(reference)
        if passage is None:
            invented += 1
            continue
        if passage.private:
            # Professor-only material may inform the answer but is never rendered as a citation a
            # student could follow; it is marked so the UI can lock it (QA-06).
            kept.setdefault(
                reference,
                CitationOut(
                    source_kind=passage.source_kind,
                    source_id=passage.source_id,
                    source_version=passage.source_version,
                    locator=passage.locator,
                    label="private supervision note",
                ),
            )
            continue
        kept.setdefault(
            reference,
            CitationOut(
                source_kind=passage.source_kind,
                source_id=passage.source_id,
                source_version=passage.source_version,
                locator=passage.locator,
                label=_label(passage),
            ),
        )

    if invented:
        metrics.CITATION_FAILURES.labels(surface="assistant").inc(invented)
        gaps.append(
            f"{invented} citation(s) in the generated answer did not match any retrieved record "
            "and were removed; treat the statements resting on them as unsupported"
        )

    for fact in computed:
        for citation in fact.citations:
            kept.setdefault(
                str(citation.source_id),
                CitationOut(
                    source_kind=citation.source_kind,
                    source_id=citation.source_id,
                    source_version=citation.source_version,
                    locator=citation.locator,
                    label=citation.label,
                ),
            )

    return list(kept.values()), gaps


def time_range(answer_scope: AnswerScope) -> str:
    """QA-03: every answer states the period it covers, including when that is "everything"."""
    if answer_scope.since and answer_scope.until:
        return f"{answer_scope.since.date()} to {answer_scope.until.date()}"
    if answer_scope.since:
        return f"{answer_scope.since.date()} to {answer_scope.as_of.date()}"
    if answer_scope.until:
        return f"up to {answer_scope.until.date()}"
    return f"all records up to {answer_scope.as_of.date()}"


def coverage_gaps(
    computed: list[Fact], passages: list[Passage], plan_notes: list[str]
) -> list[str]:
    """What the answer could not see, stated rather than left to be inferred (QA-04)."""
    gaps = list(plan_notes)
    if not passages:
        gaps.append(
            "no report or repository text matched this question, so the answer rests only on the "
            "computed facts"
        )
    for fact in computed:
        if fact.name == "stale_repositories" and fact.value:
            gaps.append(
                f"{fact.value} repository connection(s) are stale or failing, so repository "
                "evidence for this period is incomplete"
            )
    return gaps


def facts_out(computed: list[Fact]) -> list[FactOut]:
    return [
        FactOut(
            name=fact.name,
            label=fact.label,
            value=fact.value,
            as_of=fact.as_of,
            rows=fact.rows,
            note=fact.note,
        )
        for fact in computed
    ]


def _fact_payload(fact: Fact) -> dict[str, object]:
    return {
        "name": fact.name,
        "label": fact.label,
        "value": fact.value,
        "as_of": fact.as_of.isoformat(),
        "rows": fact.rows[:50],
        "note": fact.note,
    }


def _passage_payload(passage: Passage) -> dict[str, object]:
    return {
        "id": passage.citation_id,
        "source_kind": passage.source_kind,
        "locator": passage.locator,
        "source_time": passage.source_time.isoformat(),
        "private": passage.private,
        "text": passage.text[:MAX_EVIDENCE_CHARS],
    }


def _label(passage: Passage) -> str:
    when = passage.source_time.date() if isinstance(passage.source_time, datetime) else ""
    return f"{passage.source_kind} {when}".strip()
