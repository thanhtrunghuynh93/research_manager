"""The AC-19 drill the end-to-end test drives (docs/repo_layout.md §9 step 4).

Proved here as well as in the browser for a reason: the e2e run needs a Compose stack, and a
scenario that only holds when Docker is available is a scenario nobody checks on an ordinary
change. This test covers the logic; the Playwright spec covers the mail actually arriving.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications import service as notifications_service
from app.notifications.email.base import DeliveryResult
from app.seed import load_demo, run_deadline_drill

pytestmark = pytest.mark.module


class _RecordingSender:
    """Stands in for the mail provider so the test can name every address that was written to."""

    def __init__(self) -> None:
        self.to: list[str] = []

    async def send(
        self, to: str, template: str, params: dict[str, object], idempotency_key: str
    ) -> DeliveryResult:
        self.to.append(to)
        return DeliveryResult(accepted=True)


async def test_the_drill_emails_the_student_who_did_not_submit_and_not_the_others(
    db: AsyncSession,
) -> None:
    """AC-19: one email to the unsubmitted student, none to the one who submitted at 23:58 or the
    one on approved leave."""
    await load_demo(db)
    recorded = _RecordingSender()

    result = await run_deadline_drill(db, sender=recorded)

    # Stated per address rather than as a total: the demo workspace has other students with their
    # own obligations that week, and AC-19 is about who is written to, not about how many.
    assert recorded.to.count(result.unsubmitted_email) == 1
    assert result.submitted_email not in recorded.to
    assert result.excused_email not in recorded.to


async def test_a_repeated_dispatch_sends_nothing_further(db: AsyncSession) -> None:
    """AC-19: a retried job must send no duplicate."""
    await load_demo(db)
    result = await run_deadline_drill(db, sender=_RecordingSender())
    second = _RecordingSender()

    await notifications_service.dispatch_missed_deadline(db, result.period_id)
    sent_again = await notifications_service.send_queued_emails(db, second)

    assert sent_again == 0
    assert second.to == []


async def test_the_professor_sees_the_outstanding_list_in_app_and_gets_no_email(
    db: AsyncSession,
) -> None:
    """REP-08: the professor is told in-app, at the same moment, and is not mailed."""
    from app.identity import service as identity_service
    from app.identity.models import User
    from app.notifications import repository as notifications_repository
    from app.seed import PROF_EMAIL

    await load_demo(db)
    recorded = _RecordingSender()
    await run_deadline_drill(db, sender=recorded)

    from sqlalchemy import select

    professor = (await db.execute(select(User).where(User.email == PROF_EMAIL))).scalar_one()
    prof_scope = await identity_service.scope_for(db, professor)
    inbox = await notifications_repository.list_notifications(db, prof_scope)

    assert any(item.kind == "unfulfilled_obligations" for item in inbox)
    assert PROF_EMAIL not in recorded.to


async def test_the_drill_refuses_to_run_without_a_workspace(db: AsyncSession) -> None:
    """A confusing half-state helps nobody; the message says what to run first."""
    with pytest.raises(RuntimeError, match="seed demo"):
        await run_deadline_drill(db)
