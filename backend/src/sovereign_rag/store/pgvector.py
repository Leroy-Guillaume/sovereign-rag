"""pgvector-backed VectorStore.

Hybrid retrieval as ONE SQL round trip: an HNSW cosine leg and a tri-config
full-text leg (french || german || english), each ranked independently and
fused with weighted Reciprocal Rank Fusion:

    score = 1 / (rrf_k + vec_rank) + w_fts / (rrf_k + fts_rank)

The lexical leg does NOT feed the raw question to websearch_to_tsquery: the
tri-config concatenation makes every config's stopword leak back in as a
mandatory lexeme under the other two (a French question ANDs `sont`, `les`,
`de` under the german config), so any sentence-shaped query matched nothing.
Instead the query is reduced to its informative terms first (see the `terms`
CTE), matched strictly (AND) and, only when the strict pass is empty, matched
relaxed (OR) as a recall net. Measured on a 9k-chunk FR/DE/EN legal corpus:
the raw tri-config query returned 0 lexical candidates on every
sentence-shaped question.

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

# Without iterative scans, any selective predicate applied inside the vector
# leg (the Phase 2 ACL filter) silently underfills the candidate list: HNSW
# returns at most ef_search rows BEFORE the filter. relaxed_order keeps
# strict-enough ordering for a fusion that only consumes ranks.
SET_ITERATIVE_SCAN = sql.SQL("SET LOCAL hnsw.iterative_scan = relaxed_order")

# Interrogatives and modals that are stopwords in none of the three configs,
# yet carry zero retrieval intent. Measured on the evaluation corpus: `quel`
# had the highest IDF of an entire question, ahead of every content word, so
# a pure rarity gate would PROMOTE these instead of dropping them.
QUERY_STOPLIST = [
    # french
    "quel",
    "quelle",
    "quels",
    "quelles",
    "quoi",
    "comment",
    "pourquoi",
    "combien",
    "doit",
    "doivent",
    "peut",
    "peuvent",
    "faut",
    "faire",
    "dit",
    "selon",
    "concernant",
    # german
    "welche",
    "welcher",
    "welches",
    "wie",
    "warum",
    "wieso",
    "wann",
    "muss",
    "muessen",
    "kann",
    "koennen",
    "soll",
    "sollen",
    "gibt",
    "laut",
    "gemaess",
    # english
    "what",
    "which",
    "how",
    "why",
    "when",
    "does",
    "must",
    "shall",
    "should",
    "can",
    "could",
    "according",
]

# The frequency band is an EXCLUSION filter only: a term is dropped when every
# lexeme it maps to is present in more than this share of the corpus (it cannot
# discriminate). Unknown terms always pass: stale or missing statistics must
# degrade the filter, never kill the whole lexical leg.
MAX_DF_RATIO = 0.15

HYBRID_SEARCH = """\
WITH tokens AS (
  -- raw query words: lowercased, alnum-split, short words and interrogatives out
  SELECT DISTINCT tok
  FROM regexp_split_to_table(lower(%(q)s), '[^[:alnum:]]+') AS tok
  WHERE length(tok) >= 2 AND NOT (tok = ANY(%(stoplist)s))
),
terms AS (
  -- informative terms only:
  -- 1. a token that is a stopword under ANY config is dropped (it would come
  --    back as a mandatory lexeme under the other two: the tri-config leak);
  -- 2. the frequency band drops terms whose every known lexeme is too common
  --    to discriminate. min(ndoc) is NULL for terms absent from the
  --    statistics (fresh or stale lexeme_df), and NULL > x is not true, so
  --    unknown terms pass: degraded statistics weaken the filter instead of
  --    silencing the leg.
  SELECT tok FROM tokens
  WHERE to_tsvector('french', tok)  <> ''::tsvector
    AND to_tsvector('german', tok)  <> ''::tsvector
    AND to_tsvector('english', tok) <> ''::tsvector
    AND NOT coalesce(
      (SELECT min(df.ndoc) FROM lexeme_df df
       WHERE df.word = ANY (
               tsvector_to_array(to_tsvector('french', tok))
            || tsvector_to_array(to_tsvector('german', tok))
            || tsvector_to_array(to_tsvector('english', tok)))
      ) > (SELECT greatest(2, (max(total) * %(max_df)s)::int) FROM lexeme_df),
      false)
),
tsq AS (
  -- strict: AND within each config, OR across configs (|| on tsquery is OR);
  -- relaxed: OR everywhere, the recall net for when strict matches nothing.
  SELECT plainto_tsquery('french',  string_agg(tok, ' '))
      || plainto_tsquery('german',  string_agg(tok, ' '))
      || plainto_tsquery('english', string_agg(tok, ' ')) AS strict,
         websearch_to_tsquery('french',  string_agg(tok, ' or '))
      || websearch_to_tsquery('german',  string_agg(tok, ' or '))
      || websearch_to_tsquery('english', string_agg(tok, ' or ')) AS relaxed
  FROM terms
  HAVING count(*) > 0
),
vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE d.status = 'ready'
    -- Phase 2: acl_predicate() appends an EXISTS filter on document_permissions
    -- here, inside EACH leg, before fusion (never after).
  ORDER BY c.embedding <=> %(qvec)s::vector LIMIT %(n)s
),
fts_strict AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, tsq.strict) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, tsq
  WHERE d.status = 'ready'
    -- Phase 2: same acl_predicate() -- applied in EACH leg, before fusion.
    AND c.tsv @@ tsq.strict
  ORDER BY ts_rank_cd(c.tsv, tsq.strict) DESC LIMIT %(n)s
),
fts_relaxed AS (
  -- evaluated only when the strict pass is empty (the NOT EXISTS becomes a
  -- One-Time Filter InitPlan), and floored to 60%% of its own best score:
  -- better zero rows than 40 arbitrary ones.
  SELECT id, row_number() OVER (ORDER BY r DESC) AS rnk
  FROM (
    SELECT c.id, ts_rank_cd(c.tsv, tsq.relaxed) AS r,
           max(ts_rank_cd(c.tsv, tsq.relaxed)) OVER () AS rmax
    FROM chunks c JOIN documents d ON d.id = c.document_id, tsq
    WHERE d.status = 'ready'
      AND c.tsv @@ tsq.relaxed
      AND NOT EXISTS (SELECT 1 FROM fts_strict)
    ORDER BY ts_rank_cd(c.tsv, tsq.relaxed) DESC LIMIT %(n)s
  ) top
  WHERE top.r >= 0.6 * top.rmax
),
fts AS (
  SELECT id, rnk FROM fts_strict
  UNION ALL
  SELECT id, rnk FROM fts_relaxed
),
fused AS (
  SELECT c.id, c.document_id, d.filename, c.section, c.page, c.content,
         vec.rnk AS vec_rank, fts.rnk AS fts_rank,
         coalesce(1.0 / (%(rrf_k)s + vec.rnk), 0)
       + coalesce(%(w_fts)s / (%(rrf_k)s + fts.rnk), 0) AS score
  FROM vec FULL OUTER JOIN fts USING (id)
  JOIN chunks c ON c.id = coalesce(vec.id, fts.id)
  JOIN documents d ON d.id = c.document_id
)
SELECT id, document_id, filename, section, page, content, vec_rank, fts_rank, score
FROM (
  -- per-document cap: on parallel multilingual corpora the top-k otherwise
  -- fills up with near-identical chunks of one document (measured: 7 of 8).
  SELECT fused.*,
         row_number() OVER (PARTITION BY document_id ORDER BY score DESC) AS doc_rnk
  FROM fused
) diversified
WHERE %(doc_cap)s <= 0 OR doc_rnk <= %(doc_cap)s
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
        weight_fts: float = 1.0,
        per_document_cap: int = 3,
        ef_search: int = 80,
    ) -> None:
        self._pool = pool
        self._candidates = candidates
        self._rrf_k = rrf_k
        self._weight_fts = weight_fts
        self._per_document_cap = per_document_cap
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
        await conn.execute(SET_ITERATIVE_SCAN)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                HYBRID_SEARCH,
                {
                    "q": query_text,
                    "qvec": Vector(list(query_embedding)),
                    "n": self._candidates,
                    "rrf_k": self._rrf_k,
                    "w_fts": self._weight_fts,
                    "doc_cap": self._per_document_cap,
                    "stoplist": QUERY_STOPLIST,
                    "max_df": MAX_DF_RATIO,
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
