"""AUTH-01: the invitation and recovery links actually leave the building.

Until these were wired, `invite_user` emitted `InvitationCreated` and nothing listened. The
professor could issue an invitation from the roll that reached nobody, and the only copy of the
token was a line in a development log.

What the tests assert is mostly about *when* and *where*: the token travels to the invited address
and nowhere else, and the send is recorded rather than performed, because a handler runs inside a
transaction that may still roll back.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.authz import Scope
from app.core.types import Role
from app.identity import models, security
from app.identity import service as identity_service
from app.notifications import service

pytestmark = pytest.mark.module


class _Recorder:
    """Stands in for the procrastinate task, as tests/jobs/test_defer_seam.py does."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def configure(self, *, queueing_lock: str | None = None) -> _Recorder:
        return self

    async def defer_async(self, **kwargs: object) -> None:
        self.sent.append(dict(kwargs))


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    from app.notifications import scheduler_tasks

    recorder = _Recorder()
    monkeypatch.setattr(scheduler_tasks, "send_token_email", recorder)
    return recorder


async def _flush(db: AsyncSession) -> None:
    await jobs.flush_deferred(db)


async def test_an_invitation_defers_one_email_to_the_invited_address(
    db: AsyncSession, prof_scope: Scope, outbox: _Recorder
) -> None:
    await identity_service.invite_user(db, prof_scope, email="new@example.edu")

    assert outbox.sent == [], "a handler must record the send, never perform it"

    await _flush(db)

    assert len(outbox.sent) == 1
    assert outbox.sent[0]["to"] == "new@example.edu"
    assert outbox.sent[0]["template"] == service.INVITATION_TEMPLATE


async def test_the_link_carries_the_token_and_lands_on_the_acceptance_page(
    db: AsyncSession, prof_scope: Scope, outbox: _Recorder
) -> None:
    invited = await identity_service.invite_user(db, prof_scope, email="new@example.edu")
    await _flush(db)

    link = outbox.sent[0]["params"]["link"]
    assert "/accept-invitation?token=" in link
    assert link.endswith(invited.token), "the emailed token must be the one that was issued"


async def test_a_password_reset_defers_a_recovery_email(
    db: AsyncSession, student_a: models.User, outbox: _Recorder
) -> None:
    await identity_service.request_password_reset(db, email=student_a.email)
    await _flush(db)

    assert len(outbox.sent) == 1
    assert outbox.sent[0]["to"] == student_a.email
    assert outbox.sent[0]["template"] == service.PASSWORD_RESET_TEMPLATE
    assert "/reset-password?token=" in outbox.sent[0]["params"]["link"]


async def test_an_unknown_address_is_told_nothing_and_emails_nobody(
    db: AsyncSession, outbox: _Recorder
) -> None:
    """AUTH-01: the answer must not enumerate accounts, so there is nothing to send either."""
    await identity_service.request_password_reset(db, email="nobody@example.edu")
    await _flush(db)

    assert outbox.sent == []


async def test_a_rolled_back_invitation_sends_nothing(
    db: AsyncSession, prof_scope: Scope, outbox: _Recorder
) -> None:
    """The whole reason the send is deferred: an email announcing an account that never existed."""
    await identity_service.invite_user(db, prof_scope, email="new@example.edu")

    jobs.discard_deferred(db)
    await _flush(db)

    assert outbox.sent == []


async def test_the_email_names_the_workspace_and_the_person(
    db: AsyncSession, workspace: models.Workspace, prof_scope: Scope, outbox: _Recorder
) -> None:
    await identity_service.invite_user(
        db, prof_scope, email="new@example.edu", display_name="An Nguyen"
    )
    await _flush(db)

    params = outbox.sent[0]["params"]
    assert params["display_name"] == "An Nguyen"
    assert params["workspace_name"] == workspace.name


async def test_the_idempotency_key_is_the_token_digest_not_the_token(
    db: AsyncSession, prof_scope: Scope, outbox: _Recorder
) -> None:
    """A redelivered event is the same email; a reissued invitation is a different one. The key
    identifies the token without being a second copy of it."""
    invited = await identity_service.invite_user(db, prof_scope, email="new@example.edu")
    await _flush(db)

    key = outbox.sent[0]["params"]["idempotency_key"]
    assert key == security.hash_token(invited.token)
    assert invited.token not in key


async def test_an_invited_colleague_is_emailed_the_same_way(
    db: AsyncSession, prof_scope: Scope, outbox: _Recorder
) -> None:
    """ADR 0011: inviting a professor is an ordinary invitation, not a separate path."""
    await identity_service.invite_user(
        db, prof_scope, email="colleague@example.edu", role=Role.PROF
    )
    await _flush(db)

    assert outbox.sent[0]["to"] == "colleague@example.edu"
    assert outbox.sent[0]["template"] == service.INVITATION_TEMPLATE


# ------------------------------------------------------------------ the rendered message

# Rendered here rather than only deferred: the environment uses StrictUndefined, so a parameter
# the handler forgets to pass is a send-time crash the tests above cannot see — the task is stubbed
# and the template never runs.


@pytest.mark.parametrize(
    ("template", "path"),
    [
        (service.INVITATION_TEMPLATE, "accept-invitation"),
        (service.PASSWORD_RESET_TEMPLATE, "reset-password"),
    ],
)
def test_the_template_renders_with_exactly_what_the_handler_passes(
    template: str, path: str
) -> None:
    from app.notifications.templates import render

    params = {
        "display_name": "An Nguyen",
        "workspace_name": "Vision Lab",
        "link": f"https://example.edu/{path}?token=abc123",
        "expires_at": "2026-09-21",
        "idempotency_key": "digest",
    }

    subject, text, html = render(template, params)

    assert subject
    for body in (text, html):
        assert "An Nguyen" in body
        assert "Vision Lab" in body
        assert params["link"] in body
        assert "2026-09-21" in body


def test_a_token_email_carries_no_password_and_no_other_address() -> None:
    """The link is the only credential in the message, and it is the recipient's own."""
    from app.notifications.templates import render

    _, text, html = render(
        service.INVITATION_TEMPLATE,
        {
            "display_name": "An Nguyen",
            "workspace_name": "Vision Lab",
            "link": "https://example.edu/accept-invitation?token=abc123",
            "expires_at": "2026-09-21",
            "idempotency_key": "digest",
        },
    )

    for body in (text, html):
        assert "password" not in body.lower() or "choose a password" in body.lower()
        assert "@" not in body, "no address, the recipient's own included, belongs in the body"
