"""The assistant stream (architecture §11, requirements §11 "AI response time").

What the ordering has to get right: progress before anything, computed facts before generated
prose, and gaps always — including when empty, because an empty gap list is the claim that nothing
was missing rather than a section that failed to render.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.assistant import stream
from app.assistant.schemas import AnswerOut, AnswerScope, CitationOut, FactOut
from app.core.ids import uuid7

pytestmark = pytest.mark.unit


def _answer(**overrides: Any) -> AnswerOut:
    base: dict[str, Any] = {
        "id": uuid7(),
        "question": "Which reports are missing?",
        "scope": AnswerScope(as_of=datetime(2026, 9, 21, tzinfo=UTC), role="prof"),
        "time_range": "all records up to 2026-09-21",
        "answer": "One obligation is unfulfilled.",
        "facts": [
            FactOut(
                name="missing_reports",
                label="Unfulfilled obligations",
                value=1,
                as_of=datetime(2026, 9, 21, tzinfo=UTC),
            )
        ],
        "synthesis": ["The gap is on one project."],
        "suggestions": [],
        "citations": [CitationOut(source_kind="reporting_period", source_id=uuid7())],
        "gaps": [],
        "generated_at": datetime(2026, 9, 21, tzinfo=UTC),
    }
    base.update(overrides)
    return AnswerOut(**base)


async def _collect(result: AnswerOut | Exception) -> list[tuple[str, Any]]:
    async def _run() -> AnswerOut:
        if isinstance(result, Exception):
            raise result
        return result

    frames: list[tuple[str, Any]] = []
    async for chunk in stream.answer_stream(_run()):
        name = chunk.split("\n", 1)[0].removeprefix("event: ")
        data = json.loads(chunk.split("data: ", 1)[1].strip())
        frames.append((name, data))
    return frames


async def test_progress_is_emitted_before_anything_is_known() -> None:
    """The ten-second budget is mostly routing and retrieval; saying so is what makes it legible."""
    frames = await _collect(_answer())

    assert frames[0][0] == "progress"
    assert frames[0][1]["step"] == "routing"


async def test_computed_facts_arrive_before_generated_prose() -> None:
    """QA-02: they are the trustworthy half and the half that was ready first."""
    names = [name for name, _ in await _collect(_answer())]

    assert names.index("facts") < names.index("answer")


async def test_the_stream_ends_with_a_done_frame_carrying_the_answer_id() -> None:
    frames = await _collect(_answer())

    name, data = frames[-1]
    assert name == "done"
    assert data["ok"] is True
    assert data["id"]


async def test_gaps_are_sent_even_when_there_are_none() -> None:
    """An empty list is a claim that nothing was missing, not a section that failed to render."""
    frames = dict(await _collect(_answer(gaps=[])))

    assert "gaps" in frames
    assert frames["gaps"] == []


async def test_a_clarifying_question_replaces_the_answer_rather_than_joining_it() -> None:
    frames = dict(await _collect(_answer(clarifying_question="Which Lan do you mean?", answer="")))

    assert frames["clarify"]["question"] == "Which Lan do you mean?"
    assert "answer" not in frames


async def test_a_failure_is_an_event_and_the_stream_closes_cleanly() -> None:
    """A dropped EventSource makes the browser reconnect and re-ask; an error frame does not."""
    frames = await _collect(RuntimeError("provider exploded"))

    names = [name for name, _ in frames]
    assert names == ["progress", "error", "done"]
    assert frames[-1][1]["ok"] is False
    # The class name, never the message: a provider error can quote the prompt back at us.
    assert frames[1][1]["message"] == "RuntimeError"


async def test_every_frame_is_json_so_the_client_parses_one_way() -> None:
    for _name, data in await _collect(_answer()):
        assert data is not None


def test_the_headers_tell_a_proxy_not_to_buffer() -> None:
    """A buffered stream arrives all at once, which is the same as not streaming at all."""
    assert stream.SSE_HEADERS["X-Accel-Buffering"] == "no"
    assert "no-transform" in stream.SSE_HEADERS["Cache-Control"]
