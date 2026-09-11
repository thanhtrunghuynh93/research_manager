"""Splitting evidence text into retrievable pieces (architecture §5.7).

Chunking is deterministic: the same text always produces the same chunks, so re-indexing an
unchanged source is a no-op and a citation keeps pointing at the same place. Paragraph boundaries
are preferred over a fixed window, because a citation that starts mid-sentence is hard to trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 1200
MAX_CHARS = 1800
OVERLAP_CHARS = 150

_PARAGRAPH = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_no: int
    text: str
    start: int
    end: int

    @property
    def locator(self) -> str:
        """What a citation points at inside the source (QA-03)."""
        return f"chars {self.start}-{self.end}"


def chunk_text(
    text: str, *, target: int = TARGET_CHARS, maximum: int = MAX_CHARS, overlap: int = OVERLAP_CHARS
) -> list[Chunk]:
    normalised = text.strip()
    if not normalised:
        return []

    chunks: list[Chunk] = []
    for piece, start in _accumulate(normalised, target=target, maximum=maximum, overlap=overlap):
        chunks.append(
            Chunk(chunk_no=len(chunks), text=piece, start=start, end=start + len(piece))
        )
    return chunks


def _accumulate(
    text: str, *, target: int, maximum: int, overlap: int
) -> list[tuple[str, int]]:
    pieces: list[tuple[str, int]] = []
    buffer = ""
    buffer_start = 0
    cursor = 0

    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        position = text.find(paragraph, cursor)
        cursor = position + len(paragraph)

        if not buffer:
            buffer, buffer_start = paragraph, position
        elif len(buffer) + len(paragraph) + 2 <= maximum:
            buffer = f"{buffer}\n\n{paragraph}"
        else:
            pieces.append((buffer, buffer_start))
            buffer, buffer_start = paragraph, position

        while len(buffer) > maximum:
            # A single paragraph longer than the cap is split on a window with overlap, so a
            # sentence spanning the boundary is still retrievable from one side.
            pieces.append((buffer[:maximum], buffer_start))
            buffer_start += maximum - overlap
            buffer = buffer[maximum - overlap :]

        if len(buffer) >= target:
            pieces.append((buffer, buffer_start))
            buffer, buffer_start = "", cursor

    if buffer:
        pieces.append((buffer, buffer_start))
    return pieces
