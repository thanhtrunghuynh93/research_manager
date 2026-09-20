"""AUTH-01: password hashing, single-use tokens, and session expiry arithmetic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ValidationError
from app.identity import security

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


@pytest.mark.unit
def test_password_hash_is_salted_and_verifiable() -> None:
    first = security.hash_password("correct horse battery")
    second = security.hash_password("correct horse battery")

    assert first != second, "each hash carries its own salt"
    assert "correct horse battery" not in first
    assert security.verify_password("correct horse battery", first)
    assert security.verify_password("correct horse battery", second)


@pytest.mark.unit
def test_verify_password_rejects_the_wrong_password() -> None:
    stored = security.hash_password("correct horse battery")
    assert not security.verify_password("incorrect horse battery", stored)


@pytest.mark.unit
def test_verify_password_is_false_for_an_invited_user_without_a_password() -> None:
    # Users in state `invited` have no password_hash; login must fail, not raise.
    assert not security.verify_password("anything at all", None)


@pytest.mark.unit
def test_verify_password_is_false_for_a_corrupt_hash() -> None:
    assert not security.verify_password("anything at all", "not-an-argon2-hash")


@pytest.mark.unit
@pytest.mark.parametrize("password", ["", "short", "a" * (security.PASSWORD_MIN_LENGTH - 1)])
def test_password_below_the_minimum_length_is_rejected(password: str) -> None:
    with pytest.raises(ValidationError):
        security.hash_password(password)


@pytest.mark.unit
def test_a_password_of_exactly_the_minimum_length_is_accepted() -> None:
    """The boundary, pinned from both sides.

    The rejection case above is written against PASSWORD_MIN_LENGTH rather than a literal, so it
    follows the constant wherever it goes. That makes it a weaker test on its own: lower the
    minimum to one and it still passes. This is the other half — the shortest password the policy
    actually permits must work.
    """
    shortest = "a" * security.PASSWORD_MIN_LENGTH

    assert security.verify_password(shortest, security.hash_password(shortest))


@pytest.mark.unit
def test_the_minimum_length_is_not_below_the_standard_floor() -> None:
    """NIST SP 800-63B: a user-chosen secret is at least eight characters.

    Here as an assertion because the number is a policy decision that lives in one line of code,
    and the frontend duplicates it in two more. Lowering it further should require changing a test
    that says why the floor exists, rather than being a quiet edit to a constant.
    """
    assert security.PASSWORD_MIN_LENGTH >= 8


@pytest.mark.unit
def test_mint_token_returns_an_unguessable_secret_and_its_hash() -> None:
    plaintext, stored_hash = security.mint_token()
    other_plaintext, other_hash = security.mint_token()

    assert plaintext != other_plaintext
    assert stored_hash != other_hash
    assert len(plaintext) >= 32
    assert plaintext not in stored_hash, "the database never stores the token itself"
    assert security.hash_token(plaintext) == stored_hash


@pytest.mark.unit
def test_hash_token_is_stable_and_url_safe_input_tolerant() -> None:
    assert security.hash_token("abc") == security.hash_token("abc")
    assert security.hash_token("abc") != security.hash_token("abd")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Prof@Example.edu", "prof@example.edu"),
        ("  student@example.edu  ", "student@example.edu"),
        ("STUDENT@EXAMPLE.EDU", "student@example.edu"),
    ],
)
def test_normalize_email_lowercases_and_trims(raw: str, expected: str) -> None:
    assert security.normalize_email(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "   ", "no-at-sign", "no@dot", "two@@at.example"])
def test_normalize_email_rejects_malformed_addresses(raw: str) -> None:
    with pytest.raises(ValidationError):
        security.normalize_email(raw)


@pytest.mark.unit
def test_session_absolute_expiry_is_thirty_days_after_creation() -> None:
    assert security.absolute_expiry(NOW) == NOW + timedelta(days=30)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("idle", "expired"),
    [
        (timedelta(hours=11, minutes=59), False),
        (timedelta(hours=12, minutes=1), True),
    ],
)
def test_session_expires_after_twelve_idle_hours(idle: timedelta, expired: bool) -> None:
    assert security.is_idle_expired(NOW - idle, now=NOW) is expired


@pytest.mark.unit
@pytest.mark.parametrize(
    ("since", "touch"),
    [
        (timedelta(seconds=30), False),  # throttled: no write on every request
        (timedelta(seconds=90), True),
    ],
)
def test_last_seen_is_only_rewritten_once_a_minute(since: timedelta, touch: bool) -> None:
    assert security.should_touch(NOW - since, now=NOW) is touch


@pytest.mark.unit
def test_invitation_and_reset_lifetimes_match_the_architecture() -> None:
    # architecture §6.2: invitation token expires after 7 days.
    assert security.INVITATION_TTL == timedelta(days=7)
    assert security.PASSWORD_RESET_TTL <= timedelta(hours=24)
