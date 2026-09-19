"""What the professor's "analyses that did not complete" list does and does not keep (AC-13).

The list is a worklist, not a log. A retry writes a new run and leaves the old one where it was,
so without a superseded test the panel only ever grows: thirteen runs failed against a schema the
provider refused, and retrying all thirteen would have left all thirteen on screen beside the
successes, making the fix look exactly like the failure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import models, repository
from app.core.authz import Scope
from app.core.ids import uuid7

pytestmark = pytest.mark.module


def _run(
    scope: Scope,
    *,
    state: models.RunState,
    started_at: datetime,
    subject: tuple[object, object, object],
) -> models.AnalysisRun:
    student_id, project_id, period_id = subject
    return models.AnalysisRun(
        id=uuid7(),
        workspace_id=scope.workspace_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        state=state,
        started_at=started_at,
    )


async def test_a_stalled_run_that_was_later_redone_leaves_the_list(
    db: AsyncSession, prof_scope: Scope
) -> None:
    subject = (uuid7(), uuid7(), uuid7())
    now = datetime.now(UTC)
    db.add(
        _run(
            prof_scope,
            state=models.RunState.PARTIAL,
            started_at=now - timedelta(hours=2),
            subject=subject,
        )
    )
    await db.flush()

    assert len(await repository.partial_runs(db, prof_scope)) == 1

    db.add(_run(prof_scope, state=models.RunState.COMPLETED, started_at=now, subject=subject))
    await db.flush()

    assert await repository.partial_runs(db, prof_scope) == []


async def test_a_stalled_run_stays_while_only_an_earlier_one_succeeded(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # Order matters, not mere presence: a week that worked and then broke is still broken.
    subject = (uuid7(), uuid7(), uuid7())
    now = datetime.now(UTC)
    db.add(
        _run(
            prof_scope,
            state=models.RunState.COMPLETED,
            started_at=now - timedelta(hours=2),
            subject=subject,
        )
    )
    db.add(_run(prof_scope, state=models.RunState.PARTIAL, started_at=now, subject=subject))
    await db.flush()

    assert len(await repository.partial_runs(db, prof_scope)) == 1


async def test_another_weeks_success_does_not_clear_this_weeks_stall(
    db: AsyncSession, prof_scope: Scope
) -> None:
    student_id, project_id = uuid7(), uuid7()
    now = datetime.now(UTC)
    db.add(
        _run(
            prof_scope,
            state=models.RunState.PARTIAL,
            started_at=now - timedelta(hours=2),
            subject=(student_id, project_id, uuid7()),
        )
    )
    db.add(
        _run(
            prof_scope,
            state=models.RunState.COMPLETED,
            started_at=now,
            subject=(student_id, project_id, uuid7()),
        )
    )
    await db.flush()

    assert len(await repository.partial_runs(db, prof_scope)) == 1
