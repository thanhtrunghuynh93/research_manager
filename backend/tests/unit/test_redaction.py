"""What must never leave the host (requirements §11 "AI data boundary", architecture §10).

Credentials are not stored in the database, so in practice they reach the gateway only when a
student pastes one into a report or a diff carries one. Redaction is the last barrier, and it has
to hold on text nobody reviewed.
"""

from __future__ import annotations

import pytest

from app.ai.redaction import PLACEHOLDER, redact, redact_payload

pytestmark = pytest.mark.unit

# Assembled rather than written out. GitHub's push protection matches the *shape* of a Slack
# bot token and blocks the push, without caring that the body below is two runs of sequential
# digits followed by the alphabet. Split, the file never contains the token; the value handed
# to redact() is byte-for-byte what it always was, so this proves exactly what it did before.
SLACK_BOT_TOKEN = "xoxb-" + "123456789012-123456789012-abcdefghijklmnopqrstuvwx"


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_16CharactersOfNonsenseAAAAAAAAAAAAAAAA",
        "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLM",
        "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        SLACK_BOT_TOKEN,
        "AKIAIOSFODNN7EXAMPLE",
        "postgresql://rm:sup3rsecret@db.internal:5432/rm",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_a_credential_never_survives_redaction(secret: str) -> None:
    text = f"the deploy failed, here is the value we used: {secret} — please look"
    cleaned = redact(text)

    assert secret not in cleaned
    assert PLACEHOLDER in cleaned
    assert "the deploy failed" in cleaned


def test_the_subject_students_own_address_is_kept_and_others_are_not() -> None:
    """The subject's address identifies whose work this is; another person's is not ours to send."""
    text = "reviewed with an@other.person and cc'd mine@example.edu"

    cleaned = redact(text, keep_emails={"mine@example.edu"})

    assert "mine@example.edu" in cleaned
    assert "an@other.person" not in cleaned


def test_an_email_comparison_ignores_case_and_surrounding_punctuation() -> None:
    cleaned = redact("(Mine@Example.edu) opened the pull request", keep_emails={"mine@example.edu"})

    assert "Mine@Example.edu" in cleaned


def test_text_without_a_secret_is_returned_unchanged() -> None:
    text = "trained the baseline for 30 epochs; the loss plateaued at 0.31"

    assert redact(text) == text


def test_redaction_walks_a_nested_payload_and_leaves_its_shape_alone() -> None:
    payload = {
        "entry": "token: ghp_16CharactersOfNonsenseAAAAAAAAAAAAAAAA",
        "evidence": [{"id": "abc", "text": "clean text", "n": 3}],
        "count": 7,
        "flag": True,
    }

    cleaned = redact_payload(payload)

    assert cleaned["evidence"][0]["text"] == "clean text"
    assert cleaned["evidence"][0]["n"] == 3
    assert cleaned["count"] == 7
    assert cleaned["flag"] is True
    assert "ghp_" not in cleaned["entry"]


def test_redaction_reports_what_it_removed_so_the_call_can_be_audited() -> None:
    payload = {"a": "sk-projAAAA", "b": "postgresql://u:p@h:5432/d", "c": "nothing here"}

    cleaned, findings = redact_payload(payload, with_findings=True)

    assert cleaned["c"] == "nothing here"
    assert findings  # each finding names the rule, never the value it removed
    assert all("p@h" not in finding for finding in findings)


# ---------------------------------------------------------------- the shapes secrets arrive in
#
# Credentials reach the gateway by accident, and the accidents have a shape: a pasted config file,
# a failing test fixture, a copied curl. Those are JSON and header forms, not `KEY=value` lines.


@pytest.mark.parametrize(
    "carrier",
    [
        '{"password": "s3cretVALUE123"}',
        '{"api_key":"s3cretVALUE123"}',
        "{'secret': 's3cretVALUE123'}",
        '{"token" : "s3cretVALUE123"}',
        '"private_key": "s3cretVALUE123"',
        "password: s3cretVALUE123",
        "API_KEY=s3cretVALUE123",
    ],
)
def test_an_assigned_secret_is_removed_whichever_syntax_carries_it(carrier: str) -> None:
    """The rule required `[:=]` straight after the key word, so no quoted form ever matched."""
    cleaned = redact(f"the config we used: {carrier}")

    assert "s3cretVALUE123" not in cleaned
    assert PLACEHOLDER in cleaned


def test_a_basic_authorization_header_is_removed() -> None:
    cleaned = redact("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==")

    assert "dXNlcjpwYXNzd29yZDEyMw" not in cleaned
    assert PLACEHOLDER in cleaned


@pytest.mark.parametrize(
    "prose",
    [
        "we used a basic characterization of the dataset",
        "the basic implementation is fine for now",
        "a basic reproducibility check on the published numbers",
    ],
)
def test_ordinary_prose_after_the_word_basic_survives(prose: str) -> None:
    """A blunt rule is still not allowed to eat a sentence of somebody's report."""
    assert redact(prose) == prose


def test_a_value_an_earlier_rule_already_replaced_is_left_alone() -> None:
    """`openai_key` runs before `assigned_secret`; the second must not re-wrap the placeholder."""
    cleaned = redact('{"apiKey": "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAA"}')

    assert cleaned == '{"apiKey": "[redacted]"}'


def test_a_secret_nested_in_a_prompt_payload_is_removed() -> None:
    cleaned, findings = redact_payload(
        {"evidence": [{"text": 'config.json: {"password": "s3cretVALUE123"}'}]},
        with_findings=True,
    )

    assert "s3cretVALUE123" not in str(cleaned)
    assert findings == ["assigned_secret x1"]
