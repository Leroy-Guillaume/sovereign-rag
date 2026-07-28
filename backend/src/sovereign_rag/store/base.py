"""Vector store contract: chunk value types and the hybrid search Protocol."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChunkIn:
    chunk_index: int
    content: str
    embedding: list[float]
    section: str | None = None
    page: int | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
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
