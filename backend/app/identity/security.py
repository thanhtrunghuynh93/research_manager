"""Password hashing, opaque session/invitation tokens, and session lifetimes (AUTH-01).

Tokens are random secrets, never signed payloads: the database stores only their SHA-256 digest,
so a database read cannot produce a usable token and a single-use token is consumed by clearing or
stamping its row (architecture §6.2).

There is therefore no application signing key, and nothing here reads one. That is the design and
not an omission: the row is the authority, so revocation is immediate and single use is
enforceable, neither of which a self-contained signed token gives you without consulting the
database anyway. A global key was once configured (`RM_SECRET_KEY`) and read by nothing; it was
removed rather than wired up, because ending sessions is an operation, not a configuration change
— see `service.revoke_all_sessions` and docs/runbooks/rotate-secrets.md.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.errors import ValidationError

PASSWORD_MIN_LENGTH = 12
TOKEN_BYTES = 32

INVITATION_TTL = timedelta(days=7)  # architecture §6.2
PASSWORD_RESET_TTL = timedelta(hours=2)
BREAK_GLASS_RESET_TTL = timedelta(minutes=15)  # docs/runbooks/break-glass.md
SESSION_IDLE_TTL = timedelta(hours=12)
SESSION_ABSOLUTE_TTL = timedelta(days=30)
LAST_SEEN_THROTTLE = timedelta(seconds=60)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_hasher = PasswordHasher()
# Verified when a user has no password or does not exist, so login costs the same either way and
# cannot be used to enumerate accounts.
_DUMMY_HASH = _hasher.hash("dummy password for constant-time login")


def hash_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """False for a wrong password, an invited user with no password, or an unreadable hash."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (Argon2Error, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def mint_token() -> tuple[str, str]:
    """Return (token to send to the user, digest to store)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    """One spelling per address so `uq_users_email` means what it says."""
    candidate = email.strip().lower()
    if not _EMAIL_RE.match(candidate):
        raise ValidationError("invalid email address")
    return candidate


def absolute_expiry(created_at: datetime) -> datetime:
    return created_at + SESSION_ABSOLUTE_TTL


def is_idle_expired(last_seen_at: datetime, *, now: datetime) -> bool:
    return now - last_seen_at > SESSION_IDLE_TTL


def should_touch(last_seen_at: datetime, *, now: datetime) -> bool:
    """Throttle `last_seen_at` writes so an active session is not one UPDATE per request."""
    return now - last_seen_at >= LAST_SEEN_THROTTLE
