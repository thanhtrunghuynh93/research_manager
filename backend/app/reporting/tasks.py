"""Jobs owned by reporting (docs/repo_layout.md §3.2).

In this module rather than `app/tasks.py` because `reporting.artifacts` has to import it in order
to enqueue, and `app.tasks` reaches `app.observability`, which reads assessment models — a path the
layer contract refuses and should. Evidence owns its tasks for the same reason.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.db import session_factory
from app.core.jobs import RETRY_TRANSIENT, procrastinate_app

log = logging.getLogger(__name__)


@procrastinate_app.task(name="reporting.extract_artifact", retry=RETRY_TRANSIENT)
async def extract_artifact(version_id: str) -> None:
    """REP-04: read the text out of an attachment, just after the student attached it.

    Off the upload path deliberately. Unzipping a deck and embedding what comes out took the better
    part of five seconds on the live stack, and none of it is work the student has to wait through:
    the bytes are stored and the checksum has already matched by the time this runs.

    Retried, because the alternative is an attachment that is on the record and not in the index —
    present to its owner, invisible to search, and citing nothing.
    """
    from app.reporting import artifacts

    async with session_factory()() as session:
        state = await artifacts.extract_version(session, UUID(version_id))
        await session.commit()
    log.info("artifact version %s read as %s", version_id, state.value)
