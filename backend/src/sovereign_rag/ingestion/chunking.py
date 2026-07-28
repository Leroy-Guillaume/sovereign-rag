"""Per-type chunking strategies. Zero external dependencies, fully deterministic.

Both strategies share the same recursive packing: split text into paragraphs,
split oversized paragraphs into sentences, hard-cut oversized sentences, then
greedily pack units into chunks of at most `size` characters. Consecutive
chunks overlap: each new chunk starts with the last `overlap` characters of
the previous one (a verbatim tail, glued without a separator), which bounds
every chunk at `size + overlap` characters plus the optional markdown section
prefix line.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from sovereign_rag.ingestion.extract import ExtractedDoc

_PARAGRAPH_RE = re.compile(r"\n{2,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk ready for embedding; `content` is exactly what gets embedded."""

    chunk_index: int
    content: str
    section: str | None
    page: int | None


def _atomic_units(text: str, size: int) -> list[str]:
    """Paragraphs; oversized paragraphs -> sentences; oversized sentences -> hard cuts."""
    units: list[str] = []
    for raw in _PARAGRAPH_RE.split(text):
        paragraph = raw.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        for raw_sentence in _SENTENCE_RE.split(paragraph):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= size:
                units.append(sentence)
            else:
                units.extend(
                    sentence[start : start + size] for start in range(0, len(sentence), size)
                )
    return units


def _pack(units: list[str], size: int, overlap: int) -> list[str]:
    """Greedily pack units, carrying a character-level tail between chunks."""
    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) + 1 + len(unit) <= size:
            current = f"{current}\n{unit}"
            continue
        chunks.append(current)
        tail = current[-overlap:] if overlap > 0 else ""
        current = tail + unit
    if current:
        chunks.append(current)
    return chunks


def _split_markdown(doc: ExtractedDoc, size: int, overlap: int) -> list[ChunkDraft]:
    """Group fragments by section, pack each group, prefix the section path line."""
    groups: dict[str | None, list[str]] = {}
    for fragment in doc.fragments:
        groups.setdefault(fragment.section, []).append(fragment.text)

    drafts: list[ChunkDraft] = []
    for section, texts in groups.items():
        units: list[str] = []
        for text in texts:
            units.extend(_atomic_units(text, size))
        for piece in _pack(units, size, overlap):
            content = f"{section}\n{piece}" if section is not None else piece
            drafts.append(
                ChunkDraft(chunk_index=len(drafts), content=content, section=section, page=None)
            )
    return drafts


def _split_plain(doc: ExtractedDoc, size: int, overlap: int) -> list[ChunkDraft]:
    """Pack across fragments, keeping section/page of the first fragment of each chunk."""
    units: list[tuple[str, str | None, int | None]] = []
    for fragment in doc.fragments:
        units.extend(
            (unit, fragment.section, fragment.page) for unit in _atomic_units(fragment.text, size)
        )

    drafts: list[ChunkDraft] = []
    current = ""
    current_section: str | None = None
    current_page: int | None = None

    def flush() -> None:
        drafts.append(
            ChunkDraft(
                chunk_index=len(drafts),
                content=current,
                section=current_section,
                page=current_page,
            )
        )

    for text, section, page in units:
        if not current:
            current, current_section, current_page = text, section, page
            continue
        if len(current) + 1 + len(text) <= size:
            current = f"{current}\n{text}"
            continue
        flush()
        tail = current[-overlap:] if overlap > 0 else ""
        current = tail + text
        current_section, current_page = section, page
    if current:
        flush()
    return drafts


type Splitter = Callable[[ExtractedDoc, int, int], list[ChunkDraft]]

SPLITTERS: dict[str, Splitter] = {
    "md": _split_markdown,
    "pdf": _split_plain,
    "docx": _split_plain,
    "txt": _split_plain,
}


def chunk_fragments(
    doc: ExtractedDoc, *, content_type: str, size: int, overlap: int
) -> list[ChunkDraft]:
    """Chunk an extracted document using the strategy for its content type.

    Unknown content types fall back to the plain strategy (extraction already
    rejected them upstream, so this is belt and braces, not a feature).
    """
    splitter = SPLITTERS.get(content_type, _split_plain)
    return splitter(doc, size, overlap)
