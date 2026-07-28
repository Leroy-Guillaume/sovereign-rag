"""Vector store contract: chunk persistence and hybrid retrieval.

Protocol (structural typing), not ABC: implementations import nothing from here
at runtime; pyright checks conformance at the point of use.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChunkIn:
    """One chunk ready for insertion (embedding already computed by the caller)."""

    chunk_index: int
    content: str
    embedding: list[float]
    section: str | None = None
    page: int | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One fused retrieval result.

    vec_rank / fts_rank explain which leg(s) found the chunk (None = absent from
    that leg); they are persisted in the message sources snapshot for retrieval
    explainability.
    """

    chunk_id: UUID
    document_id: UUID
    filename: str
    section: str | None
    page: int | None
    content: str
    score: float  # fused RRF score
    vec_rank: int | None  # None if the hit comes from the FTS leg only
    fts_rank: int | None


class VectorStore(Protocol):
    """Contract: hybrid_search returns the k best chunks, fused across the vector
    and full-text legs with Reciprocal Rank Fusion and ordered by descending
    fused score. Only chunks of documents with status='ready' are ever returned.
    add_chunks persists a whole batch atomically. delete_document removes the
    document and all its chunks."""

    async def add_chunks(self, document_id: UUID, chunks: Sequence[ChunkIn]) -> None: ...

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        user_id: str,  # Phase 1: carried, not enforced (documented). Phase 2: ACL predicate.
        k: int = 8,
    ) -> list[SearchHit]: ...

    async def delete_document(self, document_id: UUID) -> None: ...

    async def healthcheck(self) -> None: ...
