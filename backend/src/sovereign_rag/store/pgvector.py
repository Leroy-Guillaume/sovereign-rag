"""pgvector-backed VectorStore.

Hybrid retrieval as ONE SQL round trip: an HNSW cosine leg and a tri-config
full-text leg (french || german || english), each ranked independently and
fused with Reciprocal Rank Fusion:

    score = sum over legs of 1 / (rrf_k + rank_in_leg)

RRF lives here, in SQL, because (a) the interface stays at the right altitude
("the k best chunks"), (b) the Phase 2 ACL predicate is applied inside EACH
leg before fusion, and (c) alternative stores (Qdrant, Azure AI Search) keep
their native server-side hybrid fusion behind the same Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, sql
from psycopg.rows import TupleRow, dict_row
from psycopg_pool import AsyncConnectionPool

from .base import ChunkIn, SearchHit

# SET cannot take bind parameters in the extended query protocol, so the value
# is spliced as a sql.Literal (safe: full literal quoting, and the value is an
# int validated by Settings).
SET_EF_SEARCH = sql.SQL("SET LOCAL hnsw.ef_search = {ef}")

HYBRID_SEARCH = """\
WITH query AS (
  SELECT websearch_to_tsquery('french', %(q)s)
      || websearch_to_tsquery('german', %(q)s)
      || websearch_to_tsquery('english', %(q)s) AS tsq
), vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE d.status = 'ready'
    -- Phase 2: acl_predicate() appends an EXISTS filter on document_permissions
    -- here, inside EACH leg, before fusion (never after).
  ORDER BY c.embedding <=> %(qvec)s::vector LIMIT %(n)s
), fts AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, query
  WHERE d.status = 'ready'
    -- Phase 2: same acl_predicate() -- applied in EACH leg, before fusion.
    AND c.tsv @@ query.tsq
  ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC LIMIT %(n)s
)
SELECT c.id, c.document_id, d.filename, c.section, c.page, c.content,
       vec.rnk AS vec_rank, fts.rnk AS fts_rank,
       coalesce(1.0 / (%(rrf_k)s + vec.rnk), 0)
     + coalesce(1.0 / (%(rrf_k)s + fts.rnk), 0) AS score
FROM vec FULL OUTER JOIN fts USING (id)
JOIN chunks c ON c.id = coalesce(vec.id, fts.id)
JOIN documents d ON d.id = c.document_id
ORDER BY score DESC LIMIT %(k)s
"""

INSERT_CHUNK = """\
INSERT INTO chunks (document_id, chunk_index, content, section, page, embedding)
VALUES (%(document_id)s, %(chunk_index)s, %(content)s, %(section)s, %(page)s, %(embedding)s)
"""

DELETE_DOCUMENT = "DELETE FROM documents WHERE id = %(document_id)s"

HEALTHCHECK = "SELECT 1"


class PgVectorStore:
    """VectorStore backed by Postgres: pgvector HNSW + tri-config FTS + RRF in SQL."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        candidates: int = 40,
        rrf_k: int = 60,
        ef_search: int = 80,
    ) -> None:
        self._pool = pool
        self._candidates = candidates
        self._rrf_k = rrf_k
        self._ef_search = ef_search

    async def add_chunks(self, document_id: UUID, chunks: Sequence[ChunkIn]) -> None:
        """Insert the whole batch in one transaction (all-or-nothing).

        The document stays invisible to hybrid_search until the ingestion
        service flips documents.status to 'ready' (both legs filter on it).
        """
        rows: list[dict[str, Any]] = [
            {
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "section": chunk.section,
                "page": chunk.page,
                "embedding": Vector(chunk.embedding),
            }
            for chunk in chunks
        ]
        async with self._pool.connection() as conn:
            # Per-connection and cheap (one catalog lookup); registering here keeps
            # the store independent of how the pool was configured.
            await register_vector_async(conn)
            async with conn.transaction(), conn.cursor() as cur:
                await cur.executemany(INSERT_CHUNK, rows)

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        user_id: str,
        k: int = 8,
    ) -> list[SearchHit]:
        """One transaction: SET LOCAL hnsw.ef_search, then the fused hybrid query."""
        del user_id  # Phase 1: carried, not enforced -- see the VectorStore docstring.
        async with self._pool.connection() as conn:
            await register_vector_async(conn)
            async with conn.transaction():
                rows = await self._search_in_tx(conn, query_text, query_embedding, k=k)
        return [
            SearchHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                filename=row["filename"],
                section=row["section"],
                page=row["page"],
                content=row["content"],
                score=float(row["score"]),  # numeric -> Decimal -> float
                vec_rank=row["vec_rank"],
                fts_rank=row["fts_rank"],
            )
            for row in rows
        ]

    async def _search_in_tx(
        self,
        conn: AsyncConnection[TupleRow],
        query_text: str,
        query_embedding: Sequence[float],
        *,
        k: int,
    ) -> list[dict[str, Any]]:
        """Run SET LOCAL + the hybrid query. Requires an open transaction on conn
        (SET LOCAL is transaction-scoped) and a pgvector-registered connection."""
        await conn.execute(SET_EF_SEARCH.format(ef=sql.Literal(self._ef_search)))
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                HYBRID_SEARCH,
                {
                    "q": query_text,
                    "qvec": Vector(list(query_embedding)),
                    "n": self._candidates,
                    "rrf_k": self._rrf_k,
                    "k": k,
                },
            )
            return await cur.fetchall()

    async def delete_document(self, document_id: UUID) -> None:
        """Delete the documents row; chunks disappear via ON DELETE CASCADE."""
        async with self._pool.connection() as conn:
            await conn.execute(DELETE_DOCUMENT, {"document_id": document_id})

    async def healthcheck(self) -> None:
        """Cheap probe used by /readyz; psycopg errors propagate to the caller."""
        async with self._pool.connection() as conn:
            await conn.execute(HEALTHCHECK)
