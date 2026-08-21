"""Ingestion orchestration: upload -> extract -> chunk -> embed -> store.

Processing runs in-process via asyncio tasks (no queue by design - see
ARCHITECTURE.md). NOTE: the chunk insertion (`store.add_chunks`) and the
document status update are two separate transactions BY DESIGN. The
visibility invariant is guaranteed by retrieval filtering on
`documents.status = 'ready'` plus the boot sweep that marks interrupted
'processing' documents as 'failed'; both are documented in ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from sovereign_rag.config import Settings
from sovereign_rag.embeddings.base import EmbeddingClient
from sovereign_rag.errors import ConfigError
from sovereign_rag.ingestion.chunking import chunk_fragments
from sovereign_rag.ingestion.extract import extract
from sovereign_rag.store.base import ChunkIn, VectorStore

log = structlog.get_logger(__name__)

_EMBED_BATCH_SIZE = 32
_LEXEME_REFRESH_MIN_INTERVAL_S = 60.0

_SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "txt"}

_SELECT_BY_SHA = """\
SELECT id, filename, content_type, size_bytes, status, error, owner_id, created_at
FROM documents
WHERE sha256 = %(sha256)s
"""

_VISIBLE_TO = """\
SELECT 1 FROM documents d
WHERE d.id = %(id)s
  AND (d.owner_id = %(user_id)s
       OR EXISTS (SELECT 1 FROM document_permissions p
                  WHERE p.document_id = d.id AND p.principal IN (%(user_id)s, '*')))
"""

_GRANT_ALL = """\
INSERT INTO document_permissions (document_id, principal, granted_by)
VALUES (%(document_id)s, '*', 'system:seed')
ON CONFLICT DO NOTHING
"""

_INSERT_DOCUMENT = """\
INSERT INTO documents (filename, content_type, sha256, size_bytes, status, owner_id,
                       embedding_model)
VALUES (%(filename)s, %(content_type)s, %(sha256)s, %(size_bytes)s, 'processing',
        %(owner_id)s, %(embedding_model)s)
RETURNING id, filename, content_type, size_bytes, status, error, owner_id, created_at
"""

_DELETE_STALE_CHUNKS = "DELETE FROM chunks WHERE document_id = %(id)s"

_RECLAIM_FAILED = """\
UPDATE documents SET status = 'processing', error = NULL
WHERE id = %(id)s AND status = 'failed'
RETURNING id, filename, content_type, size_bytes, status, error, owner_id, created_at
"""

_MARK_READY = "UPDATE documents SET status = 'ready', meta = %(meta)s WHERE id = %(id)s"
_MARK_FAILED = "UPDATE documents SET status = 'failed', error = %(error)s WHERE id = %(id)s"

# CONCURRENTLY: readers of the hybrid query never block on the refresh. It
# cannot run inside a transaction block, hence the autocommit connection in
# refresh_lexeme_stats().
_REFRESH_LEXEME_DF = "REFRESH MATERIALIZED VIEW CONCURRENTLY lexeme_df"


class DuplicateContentError(Exception):
    """Identical bytes already ingested by a document the requester cannot see.

    Returning the existing row would leak its metadata; silently granting
    access would turn the sha256 dedupe into a share-by-hash-probing channel.
    The route maps this to 409. The accepted trade-off (a content-hash
    existence oracle at pilot scale) is recorded in ARCHITECTURE 3.10.
    """


class IngestionService:
    """Coordinates extraction, chunking, embedding and storage for uploads."""

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        embedder: EmbeddingClient,
        store: VectorStore,
        settings: Settings,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._store = store
        self._settings = settings
        self._tasks: set[asyncio.Task[None]] = set()
        self._last_lexeme_refresh = float("-inf")
        # Embedding is the CPU-heavy stage of the pipeline. Unbounded task
        # concurrency makes N local models fight over the same cores and
        # collapses aggregate throughput (measured on a 30-document CPU
        # ingestion: zero documents completed in 25 minutes concurrently; run
        # one at a time, the largest document finished in 111 s). The
        # semaphore serializes the embedding stage only: extraction, chunking
        # and inserts still overlap freely across documents.
        self._embed_slots = asyncio.Semaphore(settings.ingestion_concurrency)

    async def ingest_upload(
        self, *, filename: str, data: bytes, content_type: str, owner_id: str
    ) -> tuple[dict[str, Any], bool]:
        """Register an upload; returns (document row, deduplicated).

        Idempotent on the sha256 of the raw bytes: a known digest returns the
        existing row with deduplicated=True and schedules nothing. A new
        digest inserts a 'processing' row, schedules background processing
        and returns immediately (the HTTP layer answers 202 long before
        processing finishes).
        """
        sha256 = hashlib.sha256(data).hexdigest()
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SELECT_BY_SHA, {"sha256": sha256})
            existing = await cur.fetchone()
            if existing is not None:
                visible = await (
                    await conn.execute(_VISIBLE_TO, {"id": existing["id"], "user_id": owner_id})
                ).fetchone()
                if visible is None:
                    raise DuplicateContentError(
                        "identical content was already ingested by another user"
                    )
                if existing["status"] != "failed":
                    return existing, True
                # A failed row must not become canonical: dedupe would answer
                # 200 forever while the content stays unsearchable (and the
                # boot sweep MANUFACTURES failed rows on every interrupted
                # ingestion). Reclaim it atomically; the status guard makes
                # two concurrent re-uploads schedule the processing once.
                await cur.execute(_RECLAIM_FAILED, {"id": existing["id"]})
                reclaimed = await cur.fetchone()
                if reclaimed is None:  # lost the race: the other upload owns it
                    return existing, True
                # A failure BETWEEN add_chunks and the ready flip leaves
                # chunks attached to the failed row; purge them so the rerun
                # starts clean. Direct SQL: the chunks table is Postgres
                # whatever the VectorStore is; an external store would need a
                # purge hook here, noted in the Protocol docstring.
                await conn.execute(_DELETE_STALE_CHUNKS, {"id": existing["id"]})
                task = asyncio.create_task(self._process(existing["id"], data, content_type))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                return reclaimed, False
            try:
                await cur.execute(
                    _INSERT_DOCUMENT,
                    {
                        "filename": filename,
                        "content_type": content_type,
                        "sha256": sha256,
                        "size_bytes": len(data),
                        "owner_id": owner_id,
                        "embedding_model": self._settings.embedding_model,
                    },
                )
            except UniqueViolation:
                # Two identical uploads raced past the dedupe SELECT; the
                # loser lands here instead of surfacing a 500. Re-reading
                # turns the race into an ordinary dedupe hit.
                await cur.execute(_SELECT_BY_SHA, {"sha256": sha256})
                raced = await cur.fetchone()
                if raced is not None:
                    return raced, True
                raise
            row = await cur.fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING always yields one row
            raise RuntimeError("INSERT INTO documents returned no row")
        task = asyncio.create_task(self._process(row["id"], data, content_type))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return row, False

    async def _process(self, document_id: UUID, data: bytes, content_type: str) -> None:
        """Background pipeline; any exception flips the document to 'failed'."""
        try:
            if self._embedder.model != self._settings.embedding_model:
                raise ConfigError(
                    f"embedding client model {self._embedder.model!r} does not match "
                    f"EMBEDDING_MODEL {self._settings.embedding_model!r}"
                )
            # Extraction is pure CPU (pypdf can chew seconds on a large
            # PDF); on the event loop it would freeze every request.
            extracted = await asyncio.to_thread(extract, data, content_type)
            drafts = chunk_fragments(
                extracted,
                content_type=content_type,
                size=self._settings.chunk_size,
                overlap=self._settings.chunk_overlap,
            )
            chunks: list[ChunkIn] = []
            async with self._embed_slots:
                for start in range(0, len(drafts), _EMBED_BATCH_SIZE):
                    batch = drafts[start : start + _EMBED_BATCH_SIZE]
                    vectors = await self._embedder.embed_documents([d.content for d in batch])
                    chunks.extend(
                        ChunkIn(
                            chunk_index=draft.chunk_index,
                            content=draft.content,
                            embedding=vector,
                            section=draft.section,
                            page=draft.page,
                        )
                        for draft, vector in zip(batch, vectors, strict=True)
                    )
            await self._store.add_chunks(document_id, chunks)
            async with self._pool.connection() as conn:
                await conn.execute(_MARK_READY, {"id": document_id, "meta": Jsonb(extracted.meta)})
            await self.refresh_lexeme_stats()
        except Exception as exc:
            log.warning("ingestion_failed", document_id=str(document_id), error=str(exc))
            async with self._pool.connection() as conn:
                await conn.execute(_MARK_FAILED, {"id": document_id, "error": str(exc)[:500]})

    async def refresh_lexeme_stats(self, *, force: bool = False) -> None:
        """Refresh the lexeme_df document-frequency snapshot used by hybrid search.

        Best-effort by design: retrieval degrades gracefully on stale (or
        empty) statistics, so a failed refresh must never fail an ingestion
        or a boot. Called after ingestions and deletions and from the boot
        sequence, and debounced: Postgres serializes concurrent refreshes of
        the same view, so a burst of documents must not queue a refresh each.

        The CONCURRENTLY refresh cannot run inside a transaction, so it runs
        on a DEDICATED autocommit connection, never on a pooled one: flipping
        autocommit on a pooled connection would leak that mode to every later
        borrower and silently strip them of their implicit transactions.
        """
        now = time.monotonic()
        if not force and now - self._last_lexeme_refresh < _LEXEME_REFRESH_MIN_INTERVAL_S:
            return
        self._last_lexeme_refresh = now
        try:
            conninfo = self._pool.conninfo
            if not isinstance(conninfo, str):  # pragma: no cover - create_pool passes a str
                raise ConfigError("refresh_lexeme_stats requires a conninfo-string pool")
            conn = await AsyncConnection.connect(conninfo, autocommit=True)
            try:
                await conn.execute(_REFRESH_LEXEME_DF)
            finally:
                await conn.close()
        except Exception as exc:
            log.warning("lexeme_stats_refresh_failed", error=str(exc))

    async def wait_idle(self) -> None:
        """Wait for every in-flight ingestion task (used by tests and the demo seed)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def seed_demo(self, demo_dir: Path) -> None:
        """Ingest every supported file in `demo_dir` as user 'system'.

        Idempotent thanks to the sha256 dedupe, so calling it on every boot
        is free once the corpus is in. The parameter name is part of the
        contract: Task 16 calls `seed_demo(demo_dir)` from the lifespan.
        """
        if not demo_dir.is_dir():
            return
        for path in sorted(demo_dir.iterdir()):
            content_type = _SUPPORTED_EXTENSIONS.get(path.suffix.lower())
            if content_type is None:
                continue
            row, _ = await self.ingest_upload(
                filename=path.name,
                data=path.read_bytes(),
                content_type=content_type,
                owner_id="system",
            )
            # The demo corpus exists to be searched by whoever signs in with a
            # demo key: grant it to everyone, like the Phase 1 backfill.
            async with self._pool.connection() as conn:
                await conn.execute(_GRANT_ALL, {"document_id": row["id"]})
        await self.wait_idle()
