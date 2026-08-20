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
            tail = current.content.split("\n", 1)[0]
            # the carried tail is a word-aligned suffix of the previous chunk...
            assert tail
            assert previous.content.endswith(tail)
            boundary = previous.content[-len(tail) - 1]
            assert boundary.isspace(), "tail must start on a word boundary"
            # ...and never longer than the configured overlap
            assert len(tail) <= 50


def test_overlap_never_fabricates_half_words() -> None:
    """A tail cut inside a word must drop the half-word, not index it."""
    doc = ExtractedDoc(fragments=[Fragment(text=LOREM * 10)], meta={})
    chunks = chunk_fragments(doc, content_type="txt", size=200, overlap=50)
    vocabulary = set(LOREM.replace(".", "").lower().split())
    for chunk in chunks[1:]:
        first_word = chunk.content.split(None, 1)[0].strip(".").lower()
        assert first_word in vocabulary, f"fabricated half-word {first_word!r}"


def test_plain_chunks_carry_a_context_header() -> None:
    """PDF/DOCX/TXT chunks must carry section or title in their indexed text."""
    with_sections = ExtractedDoc(
        fragments=[Fragment(text="Scope of the policy.", section="Chapter 1")],
        meta={"title": "Security Policy"},
    )
    chunks = chunk_fragments(with_sections, content_type="docx", size=1200, overlap=200)
    assert chunks[0].content == "Chapter 1\nScope of the policy."

    title_only = ExtractedDoc(
        fragments=[Fragment(text="Scanned paragraph.", page=3)],
        meta={"title": "ISO 27001 overview"},
    )
    chunks = chunk_fragments(title_only, content_type="pdf", size=1200, overlap=200)
    assert chunks[0].content == "ISO 27001 overview\nScanned paragraph."
    assert chunks[0].page == 3

    bare = ExtractedDoc(fragments=[Fragment(text="No metadata at all.")], meta={})
    chunks = chunk_fragments(bare, content_type="txt", size=1200, overlap=200)
    assert chunks[0].content == "No metadata at all."


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
