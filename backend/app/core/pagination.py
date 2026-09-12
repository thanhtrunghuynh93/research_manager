"""Opaque cursor pagination shared by list endpoints."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import orjson
from pydantic import BaseModel, Field

from app.core.errors import ValidationError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    items: Sequence[T]
    next_cursor: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


def encode_cursor(values: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(orjson.dumps(values)).decode()


def decode_cursor(cursor: str | None) -> dict[str, object] | None:
    if not cursor:
        return None
    try:
        decoded = orjson.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, orjson.JSONDecodeError) as exc:
        raise ValidationError("invalid cursor") from exc
    if not isinstance(decoded, dict):
        raise ValidationError("invalid cursor")
    return decoded


def cursor_after(cursor: str | None) -> UUID | None:
    """The id a keyset page resumes from, or None for the first page.

    The key lookup and the UUID parse live here rather than at each call site, because a cursor is
    opaque client input: `decoded["after"]` raised KeyError and `UUID(...)` raised ValueError, and
    both reached the catch-all handler as a 500 with a logged stack trace for what is simply a
    malformed request.
    """
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    try:
        return UUID(str(decoded["after"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor") from exc


async def collect_all[T](
    fetch: Callable[[str | None], Awaitable[Page[T]]], *, cap: int = 10_000
) -> list[T]:
    """Follow the cursor to the end, for a caller that needs every row rather than a page.

    A list endpoint is paginated because a client scrolls; a server-side reader that resolves a
    name or builds an export is not scrolling, and stopping at the first page made it silently
    wrong — a student past the two-hundredth row was "no such student", and an export that
    declares itself complete was not.

    `cap` is a guard against an unbounded loop, not a page size. Reaching it is a bug, not a
    workload, so it says so rather than truncating quietly.
    """
    items: list[T] = []
    cursor: str | None = None
    while True:
        page = await fetch(cursor)
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items
        if len(items) >= cap:
            raise ValidationError(f"more than {cap} rows to read in one pass")


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))
