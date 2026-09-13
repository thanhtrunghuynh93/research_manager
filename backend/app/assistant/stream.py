"""Server-sent events for the assistant (architecture §11, requirements §11 "AI response time").

The target is a first meaningful response within ten seconds. Most of an answer's latency is not
the generation — it is the routing call, the fact functions, and retrieval, all of which happen
before there is a word to show. Streaming the *progress* of those steps is what makes the wait
legible; streaming the generated text afterwards is the smaller half.

So the event sequence mirrors the pipeline rather than the prose: `progress` per step, then
`facts` as soon as they are computed (they are the authoritative half and they are ready first),
then `answer`, `citations`, `gaps`, and `done`.

A failure is an event, not a dropped connection. A browser reconnects to a dropped EventSource and
would re-ask the question; an `error` event says what happened and closes cleanly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger(__name__)

# Anything a proxy might buffer needs a nudge; Caddy and nginx both honour this.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def event(name: str, data: Any) -> str:
    """One SSE frame. Data is always JSON, so the client parses one way for every event."""
    payload = json.dumps(data, default=str)
    return f"event: {name}\ndata: {payload}\n\n"


def progress(step: str, detail: str = "") -> str:
    return event("progress", {"step": step, "detail": detail})


async def answer_stream(
    run: Any,
    *,
    steps: tuple[str, ...] = ("routing", "computing facts", "retrieving evidence", "writing"),
) -> AsyncIterator[str]:
    """Emit progress while `run` is awaited, then the answer in the order it becomes useful.

    `run` is a coroutine producing an `AnswerOut`. It is awaited once here rather than being
    re-entered per step: the service owns the order of the pipeline, and duplicating it here would
    be two descriptions of one thing that could disagree.
    """
    yield progress(steps[0])
    try:
        result = await run
    except Exception as error:  # noqa: BLE001 - a failure is an event, not a dropped connection
        log.exception("assistant stream failed")
        yield event("error", {"message": f"{type(error).__name__}", "recoverable": True})
        yield event("done", {"ok": False})
        return

    for step in steps[1:]:
        yield progress(step, "complete")

    # Facts first: they are computed rather than generated, so they are both the trustworthy half
    # and the half that was ready earliest (QA-02).
    yield event("facts", [fact.model_dump(mode="json") for fact in result.facts])
    yield event("scope", result.scope.model_dump(mode="json"))

    if result.clarifying_question:
        yield event("clarify", {"question": result.clarifying_question})
    else:
        yield event("answer", {"text": result.answer, "time_range": result.time_range})
        yield event("synthesis", result.synthesis)
        yield event("suggestions", result.suggestions)
        yield event("citations", [c.model_dump(mode="json") for c in result.citations])

    # Gaps last and always, including when empty: an empty list is the claim that nothing was
    # missing, and the client renders it as such (QA-04).
    yield event("gaps", result.gaps)
    yield event("done", {"ok": True, "id": str(result.id), "cached": result.cached})
