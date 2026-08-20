"""Prompt construction for the RAG chat.

THE system prompt lives here, visible and versioned in code: it is part of the
observable behaviour of the assistant and must be reviewable in diffs.
`build_messages` is pure so tests can assert the exact prompt sent to the LLM.
"""

from collections.abc import Callable, Sequence
from typing import Any

from ..llm.base import ChatMessage
from ..store.base import SearchHit

SYSTEM_PROMPT = """\
You are a careful documentation assistant.
Answer the question using ONLY the numbered context passages provided below.
Cite every passage you rely on with its bracketed number, e.g. [1] or [2][3].
Answer in the language of the question.
If the context does not contain the answer, say so explicitly; never invent facts."""

NO_CONTEXT_INSTRUCTION = (
    "No relevant passage was found for this question. State clearly, in the "
    "language of the question, that nothing relevant was found in the document "
    "base. Do not answer from your own knowledge."
)

EXCERPT_LENGTH = 500


def _context_block(index: int, hit: SearchHit, redact: Callable[[str], str]) -> str:
    """Format one hit as a numbered context block (filename, section, page, content)."""
    location = hit.filename
    if hit.section:
        location += f" - {hit.section}"
    if hit.page is not None:
        location += f" - page {hit.page}"
    return f"[{index}] {location}:\n{redact(hit.content)}"


def build_messages(
    history: Sequence[ChatMessage],
    question: str,
    hits: Sequence[SearchHit],
    redact: Callable[[str], str] = lambda text: text,  # no-op: the Phase 2 PII (Presidio) seam
) -> list[ChatMessage]:
    """Assemble [system (+ numbered context)] + history + [question].

    Every context block goes through ``redact`` before reaching the LLM; the
    default is a documented no-op that Phase 2 replaces with a Presidio-backed
    redactor. With zero hits the system prompt carries NO_CONTEXT_INSTRUCTION
    instead of context: the LLM is still called and answers honestly.
    """
    if hits:
        blocks = "\n\n".join(_context_block(i, hit, redact) for i, hit in enumerate(hits, start=1))
        system = f"{SYSTEM_PROMPT}\n\nContext:\n\n{blocks}"
    else:
        system = f"{SYSTEM_PROMPT}\n\n{NO_CONTEXT_INSTRUCTION}"
    return [
        ChatMessage(role="system", content=system),
        *history,
        ChatMessage(role="user", content=question),
    ]


def hits_to_sources(hits: Sequence[SearchHit]) -> list[dict[str, Any]]:
    """SourceOut-shaped dicts: SSE ``sources`` event payload and jsonb audit snapshot.

    UUIDs are serialized to strings so the result is json.dumps-able as-is; the
    snapshot must survive document deletion (LIPAD traceability), hence values,
    not foreign keys.
    """
    return [
        {
            "chunk_id": str(hit.chunk_id),
            "document_id": str(hit.document_id),
            "filename": hit.filename,
            "section": hit.section,
            "page": hit.page,
            "excerpt": hit.content[:EXCERPT_LENGTH],
            "score": hit.score,
            "vec_rank": hit.vec_rank,
            "fts_rank": hit.fts_rank,
        }
        for hit in hits
    ]
