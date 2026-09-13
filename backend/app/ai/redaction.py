"""The last barrier before text leaves the host (requirements §11, architecture §10).

Credentials are never stored in the database, so they reach this point only by accident: a student
pastes a token into a report, a diff carries a connection string, a stack trace quotes a key. None
of that is research evidence and none of it should be sent to a provider, so it is removed here
rather than trusted not to appear.

Two rules, both deliberately blunt:
  - anything that looks like a credential is replaced, even at the cost of a false positive, since
    losing a sentence of a report is a smaller harm than leaking a key;
  - every email address except the subject's own is replaced, because whose work this is matters
    and everyone else's identity does not.

What was removed is reported as a rule name, never as the value, so a call can be audited without
the audit trail itself becoming the leak.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal, overload

PLACEHOLDER = "[redacted]"
EMAIL_PLACEHOLDER = "[redacted-email]"

# Ordered: the most specific patterns first, so a connection string is not half-eaten by the
# generic key rule before its password is seen.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "connection_string",
        re.compile(r"\b[a-z][a-z0-9+.\-]{2,}://[^\s/@:]+:[^\s/@]+@[^\s]+", re.IGNORECASE),
    ),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{8,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|AIDA|AGPA)[A-Z0-9]{12,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}\b")),
    ("bearer_header", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "basic_header",
        # The lookahead keeps ordinary prose out: a real credential carries a digit, `+`, `/` or
        # padding, where "basic characterization" does not.
        re.compile(r"\b[Bb]asic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{16,}={0,2}"),
    ),
    (
        "assigned_secret",
        # `api_key = "…"`, `PASSWORD: …`, `secret=…`, `"password": "…"` — the shape, not the
        # value. The optional quote before the separator is what makes the JSON form match: in
        # `{"password": "x"}` the closing quote of the key sits between the word and the colon,
        # so a pattern that went straight from `\b` to `[:=]` saw nothing at all.
        re.compile(
            r"\b(?:api[_\-]?key|secret|password|passwd|token|private[_\-]?key)\b"
            # The lookahead leaves a value an earlier, more specific rule already replaced
            # alone; re-matching it would append a second closing bracket.
            r"[\"']?\s*[:=]\s*[\"']?(?!\[redacted)([^\s\"',;}\]]{8,})[\"']?",
            re.IGNORECASE,
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
]

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def redact(text: str, *, keep_emails: Iterable[str] = ()) -> str:
    """Return `text` with credentials removed and foreign email addresses replaced."""
    cleaned, _ = _redact_text(text, keep_emails=keep_emails)
    return cleaned


def _redact_text(text: str, *, keep_emails: Iterable[str] = ()) -> tuple[str, list[str]]:
    if not text:
        return text, []

    findings: list[str] = []
    cleaned = text
    for name, pattern in _RULES:
        cleaned, count = pattern.subn(_replacement_for(name), cleaned)
        if count:
            findings.append(f"{name} x{count}")

    keep = {address.strip().lower() for address in keep_emails}

    def _email(match: re.Match[str]) -> str:
        if match.group(0).lower() in keep:
            return match.group(0)
        findings.append("email")
        return EMAIL_PLACEHOLDER

    cleaned = _EMAIL.sub(_email, cleaned)
    return cleaned, _tally(findings)


def _replacement_for(name: str) -> Any:
    if name != "assigned_secret":
        return PLACEHOLDER

    # Keep the key name so the sentence still reads; drop only the value.
    def _keep_the_label(match: re.Match[str]) -> str:
        whole, value = match.group(0), match.group(1)
        return whole.replace(value, PLACEHOLDER)

    return _keep_the_label


def _tally(findings: list[str]) -> list[str]:
    """Collapse repeated rule names into one entry each, so the report stays short."""
    counts: dict[str, int] = {}
    for finding in findings:
        name, _, suffix = finding.partition(" x")
        counts[name] = counts.get(name, 0) + (int(suffix) if suffix else 1)
    return [f"{name} x{count}" for name, count in sorted(counts.items())]


@overload
def redact_payload(
    payload: dict[str, Any],
    *,
    keep_emails: Iterable[str] = ...,
    with_findings: Literal[False] = ...,
) -> dict[str, Any]: ...


@overload
def redact_payload(
    payload: dict[str, Any],
    *,
    keep_emails: Iterable[str] = ...,
    with_findings: Literal[True],
) -> tuple[dict[str, Any], list[str]]: ...


def redact_payload(
    payload: dict[str, Any],
    *,
    keep_emails: Iterable[str] = (),
    with_findings: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], list[str]]:
    """Redact every string anywhere in a prompt payload, leaving its shape untouched.

    The gateway sends nested structures — evidence lists, verdicts, rubric definitions — and a
    secret is as likely to sit three levels down as at the top.
    """
    findings: list[str] = []

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            cleaned, found = _redact_text(value, keep_emails=keep_emails)
            findings.extend(found)
            return cleaned
        if isinstance(value, dict):
            return {key: _walk(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_walk(item) for item in value]
        return value

    cleaned_payload: dict[str, Any] = _walk(payload)
    if with_findings:
        return cleaned_payload, _tally(findings)
    return cleaned_payload
