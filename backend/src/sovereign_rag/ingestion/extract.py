"""Text extraction: raw file bytes -> ExtractedDoc (positioned text fragments).

Supported types: pdf (pypdf), docx (python-docx), md and txt (stdlib only).
Deliberate limits, documented in the README: no OCR (scanned PDFs fail with an
explicit error) and PDF tables come out as plain text lines.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from docx import Document  # pyright: ignore[reportMissingTypeStubs]
from docx.table import Table  # pyright: ignore[reportMissingTypeStubs]
from docx.text.paragraph import Paragraph  # pyright: ignore[reportMissingTypeStubs]
from pypdf import PdfReader

from sovereign_rag.errors import ExtractionError

_NO_TEXT_MSG = "no extractable text (scanned PDF? OCR is out of scope, see README)"
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True, slots=True)
class Fragment:
    """One extracted piece of text with its position metadata."""

    text: str
    section: str | None = None  # heading path, e.g. "Setup > Docker" (md/docx)
    page: int | None = None  # 1-based page number (pdf only)


@dataclass
class ExtractedDoc:
    """Extraction result: ordered fragments plus file-level metadata."""

    fragments: list[Fragment]
    meta: dict[str, str]  # "title"/"author" when the file provides them


def extract(data: bytes, content_type: str) -> ExtractedDoc:
    """Dispatch on content_type ('pdf' | 'docx' | 'md' | 'txt')."""
    match content_type:
        case "pdf":
            return _extract_pdf(data)
        case "docx":
            return _extract_docx(data)
        case "md":
            return _extract_md(data)
        case "txt":
            return _extract_txt(data)
        case _:
            raise ExtractionError(f"unsupported content type: {content_type!r}")


def _extract_pdf(data: bytes) -> ExtractedDoc:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # pypdf raises many exception types on corrupt files
        raise ExtractionError(f"unreadable PDF: {exc}") from exc

    fragments: list[Fragment] = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            continue  # blank or image-only page
        fragments.append(Fragment(text=text.strip(), page=number))

    if len("".join(f.text for f in fragments).strip()) < 20:
        raise ExtractionError(_NO_TEXT_MSG)

    meta: dict[str, str] = {}
    info = reader.metadata
    if info is not None:
        if info.title:
            meta["title"] = info.title
        if info.author:
            meta["author"] = info.author
    return ExtractedDoc(fragments=fragments, meta=meta)


def _extract_docx(data: bytes) -> ExtractedDoc:
    document = Document(io.BytesIO(data))
    fragments: list[Fragment] = []
    stack: list[str] = []  # one heading text per level; joined with " > "

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            level = _heading_level(item)
            if level is not None:
                if text:
                    del stack[level - 1 :]
                    stack.append(text)
                continue
            if text:
                fragments.append(Fragment(text=text, section=_section(stack)))
        # python-docx has no py.typed marker, so its inferred Paragraph | Table union
        # is not authoritative; keep the runtime check as a guard.
        elif isinstance(item, Table):  # pyright: ignore[reportUnnecessaryIsInstance]
            rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in item.rows]
            table_text = "\n".join(row for row in rows if row.strip(" |"))
            if table_text:
                fragments.append(Fragment(text=table_text, section=_section(stack)))

    meta: dict[str, str] = {}
    props = document.core_properties
    if props.title:
        meta["title"] = props.title
    if props.author:
        meta["author"] = props.author
    return ExtractedDoc(fragments=fragments, meta=meta)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    name = style.name if style is not None else None
    if name is not None and name.startswith("Heading "):
        suffix = name.removeprefix("Heading ")
        if suffix.isdigit():
            return int(suffix)
    return None


def _extract_md(data: bytes) -> ExtractedDoc:
    text = _decode(data)
    fragments: list[Fragment] = []
    stack: list[str] = []
    block: list[str] = []

    def flush() -> None:
        content = "\n".join(block).strip()
        if content:
            fragments.append(Fragment(text=content, section=_section(stack)))
        block.clear()

    for line in text.splitlines():
        matched = _MD_HEADING.match(line)
        if matched:
            flush()
            level = len(matched.group(1))
            del stack[level - 1 :]
            stack.append(matched.group(2))
        else:
            block.append(line)
    flush()
    return ExtractedDoc(fragments=fragments, meta={})


def _extract_txt(data: bytes) -> ExtractedDoc:
    text = _decode(data).strip()
    fragments = [Fragment(text=text)] if text else []
    return ExtractedDoc(fragments=fragments, meta={})


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _section(stack: list[str]) -> str | None:
    return " > ".join(stack) if stack else None
