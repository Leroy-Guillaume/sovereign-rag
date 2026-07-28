"""Tests for ingestion.chunking: size tolerance, overlap, ordering, determinism."""

from sovereign_rag.ingestion.chunking import chunk_fragments
from sovereign_rag.ingestion.extract import ExtractedDoc, Fragment

LOREM = (
    "Retrieval augmented generation grounds answers in your own documents. "
    "It keeps sensitive data inside your infrastructure. "
    "Hybrid search combines vector similarity with keyword matching. "
)


def _md_doc() -> ExtractedDoc:
    return ExtractedDoc(
        fragments=[
            Fragment(text=LOREM * 8),
            Fragment(text=LOREM * 12, section="Overview"),
            Fragment(text=LOREM * 12, section="Overview > Retrieval"),
            Fragment(text=LOREM * 4, section="Compliance"),
        ],
        meta={},
    )


def test_every_chunk_within_size_tolerance() -> None:
    chunks = chunk_fragments(_md_doc(), content_type="md", size=300, overlap=80)
    assert len(chunks) > 4
    assert all(len(c.content) <= 300 + 200 for c in chunks)


def test_consecutive_chunks_share_overlap() -> None:
    doc = ExtractedDoc(fragments=[Fragment(text=LOREM * 10)], meta={})
    chunks = chunk_fragments(doc, content_type="txt", size=200, overlap=50)
    assert len(chunks) >= 3
    for previous, current in zip(chunks, chunks[1:], strict=False):  # noqa: RUF007
        if len(previous.content) >= 50:  # previous chunk long enough to donate a tail
            assert current.content.startswith(previous.content[-50:])


def test_chunk_index_contiguous_from_zero() -> None:
    chunks = chunk_fragments(_md_doc(), content_type="md", size=300, overlap=80)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_md_sections_preserved_and_prefixed() -> None:
    doc = ExtractedDoc(
        fragments=[
            Fragment(text="Intro text."),
            Fragment(text="Install steps.", section="Setup"),
            Fragment(text="Compose info.", section="Setup > Docker"),
        ],
        meta={},
    )
    chunks = chunk_fragments(doc, content_type="md", size=1200, overlap=200)
    assert [(c.content, c.section) for c in chunks] == [
        ("Intro text.", None),
        ("Setup\nInstall steps.", "Setup"),
        ("Setup > Docker\nCompose info.", "Setup > Docker"),
    ]


def test_page_propagated_for_pdf_fragments() -> None:
    pages = [("p1 " * 30).strip(), ("p2 " * 30).strip(), ("p3 " * 30).strip()]
    doc = ExtractedDoc(
        fragments=[Fragment(text=text, page=n) for n, text in enumerate(pages, start=1)],
        meta={},
    )
    chunks = chunk_fragments(doc, content_type="pdf", size=120, overlap=20)
    assert [c.page for c in chunks] == [1, 2, 3]
    assert all(c.section is None for c in chunks)


def test_deterministic() -> None:
    first = chunk_fragments(_md_doc(), content_type="md", size=300, overlap=80)
    second = chunk_fragments(_md_doc(), content_type="md", size=300, overlap=80)
    assert first == second


def test_pathological_single_long_paragraph_still_splits() -> None:
    doc = ExtractedDoc(fragments=[Fragment(text="x" * 10_000)], meta={})
    chunks = chunk_fragments(doc, content_type="txt", size=1200, overlap=200)
    assert len(chunks) >= 8
    assert all(len(c.content) <= 1200 + 200 for c in chunks)
