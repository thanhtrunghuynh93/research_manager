"""Identifiers: time-ordered UUIDv7 for every primary key."""

from __future__ import annotations

from uuid import UUID

import uuid6


def uuid7() -> UUID:
    return UUID(bytes=uuid6.uuid7().bytes)
