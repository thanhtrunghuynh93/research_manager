"""Chunking has to be deterministic: a citation points at a place, not at a moment."""

from __future__ import annotations

import pytest

from app.evidence.index.chunking import MAX_CHARS, chunk_text

pytestmark = pytest.mark.unit


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_text("We reproduced the baseline within one point.")

    assert len(chunks) == 1
    assert chunks[0].chunk_no == 0
    assert chunks[0].text.startswith("We reproduced")


def test_the_same_text_always_chunks_the_same_way() -> None:
    text = "\n\n".join(f"Paragraph {index} about the evaluation." for index in range(40))

    assert [c.text for c in chunk_text(text)] == [c.text for c in chunk_text(text)]


def test_no_chunk_exceeds_the_cap() -> None:
    text = "\n\n".join("x" * 700 for _ in range(10))

    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunk_text(text))


def test_a_single_huge_paragraph_is_split_with_overlap() -> None:
    chunks = chunk_text("y" * (MAX_CHARS * 2))

    assert len(chunks) > 1
    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunks)


def test_paragraphs_are_kept_together_when_they_fit() -> None:
    chunks = chunk_text("First paragraph.\n\nSecond paragraph.")

    assert len(chunks) == 1
    assert "First paragraph." in chunks[0].text
    assert "Second paragraph." in chunks[0].text


def test_a_chunk_knows_where_it_came_from() -> None:
    chunks = chunk_text("\n\n".join("z" * 900 for _ in range(4)))

    assert chunks[0].locator.startswith("chars 0-")
    assert all(chunk.end > chunk.start for chunk in chunks)
    assert [chunk.chunk_no for chunk in chunks] == list(range(len(chunks)))


def test_vietnamese_text_is_not_mangled() -> None:
    text = "Tuần này tôi đã hoàn thành bộ nạp dữ liệu.\n\nKết quả tái lập đúng kích thước."

    chunks = chunk_text(text)

    assert len(chunks) == 1
    assert "hoàn thành" in chunks[0].text
