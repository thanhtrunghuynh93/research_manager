"""Opaque cursor pagination shared by list endpoints."""

from __future__ import annotations

import base64
from collections.abc import Sequence

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


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))
