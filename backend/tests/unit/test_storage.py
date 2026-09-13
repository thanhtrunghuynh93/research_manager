"""The object-store seam (architecture §5.6, REP-04).

Two properties the rest of the system leans on. Keys are derived from ids and a content hash, never
from a filename, because a filename is user input and a key is a path. And the API never streams a
file body: it hands out a time-limited URL after the permission check, which is what keeps a 25 MB
upload off the application process entirely.
"""

from __future__ import annotations

import pytest

from app.core.ids import uuid7
from app.core.storage import InMemoryObjectStore, extracted_text_key, storage_key

pytestmark = pytest.mark.unit


def test_a_key_is_built_from_ids_and_a_hash_not_from_the_filename() -> None:
    workspace, artifact = uuid7(), uuid7()

    key = storage_key(
        workspace_id=workspace,
        artifact_id=artifact,
        version_no=2,
        sha256="a" * 64,
        filename="../../etc/passwd",
    )

    assert key == f"{workspace}/artifacts/{artifact}/2/{'a' * 64}"
    assert ".." not in key


def test_a_known_extension_is_kept_so_the_object_is_recognisable() -> None:
    key = storage_key(
        workspace_id=uuid7(),
        artifact_id=uuid7(),
        version_no=1,
        sha256="b" * 64,
        filename="figure-3.PNG",
    )

    assert key.endswith(".png")


def test_an_unknown_or_dangerous_extension_is_dropped_rather_than_carried() -> None:
    key = storage_key(
        workspace_id=uuid7(),
        artifact_id=uuid7(),
        version_no=1,
        sha256="c" * 64,
        filename="payload.sh",
    )

    assert key.endswith("c" * 64)


def test_the_extracted_text_sits_beside_its_original() -> None:
    original = storage_key(
        workspace_id=uuid7(),
        artifact_id=uuid7(),
        version_no=1,
        sha256="d" * 64,
        filename="paper.pdf",
    )

    assert extracted_text_key(original).endswith("/extracted.txt")
    assert extracted_text_key(original).startswith(original.rsplit("/", 1)[0])


async def test_the_in_memory_store_round_trips_and_reports_what_it_holds() -> None:
    store = InMemoryObjectStore()

    await store.put_bytes("a/b/c", b"hello", content_type="text/plain")

    assert await store.get_bytes("a/b/c") == b"hello"
    assert await store.exists("a/b/c")
    assert (await store.head("a/b/c")).byte_size == 5


async def test_a_missing_object_is_absent_rather_than_an_exception() -> None:
    store = InMemoryObjectStore()

    assert await store.exists("nothing") is False
    assert await store.get_bytes("nothing") is None


async def test_presigned_urls_are_time_limited_and_mention_the_key() -> None:
    store = InMemoryObjectStore()

    put = await store.presigned_put("a/b/c", content_type="application/pdf", expires_in=900)
    get = await store.presigned_get("a/b/c", expires_in=300)

    assert "a/b/c" in put.url and put.expires_in == 900
    assert "a/b/c" in get.url and get.expires_in == 300


async def test_deleting_removes_the_object_and_is_safe_to_repeat() -> None:
    """Retention has to be able to finish even when a previous sweep got halfway."""
    store = InMemoryObjectStore()
    await store.put_bytes("a/b/c", b"x", content_type="text/plain")

    await store.delete("a/b/c")
    await store.delete("a/b/c")

    assert await store.exists("a/b/c") is False
