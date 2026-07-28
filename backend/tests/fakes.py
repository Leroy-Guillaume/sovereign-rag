"""Deterministic test doubles for the three provider Protocols, plus make_settings.

Test-only helpers: deliberately NOT part of the sovereign_rag package (no
public testing API to maintain). The InMemoryVectorStore mirrors the RRF
fusion that store/pgvector.py performs in SQL, in pure Python.
"""

import hashlib
import math
import random
import re
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sovereign_rag.config import Settings
from sovereign_rag.errors import ProviderError
from sovereign_rag.llm.base import ChatMessage, CompletionChunk
from sovereign_rag.store.base import ChunkIn, SearchHit


def make_settings(**overrides: Any) -> Settings:
    """Settings for tests: no .env file, deterministic auth keys, demo seed off."""
    values: dict[str, Any] = {
        "auth_api_keys": {
            "test-key-alice": "alice",
            "test-key-bob": "bob",
            "test-key-admin": "admin",
        },
        "auth_admin_users": {"admin"},
        "seed_demo_data": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


class FakeLLM:
    """Scripted LLMClient: yields `chunks`, then one final usage-only chunk.

    fail_after=N raises ProviderError("fake failure") after N content chunks
    (and suppresses the usage chunk), simulating a mid-stream provider
    failure. stream_chat records its messages on last_messages at call time,
    before iteration starts.
    """

    def __init__(
        self,
        chunks: list[str] | None = None,
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        fail_after: int | None = None,
    ) -> None:
        self.model = "fake/fake"
        self.chunks = chunks if chunks is not None else ["Hello", " world"]
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.fail_after = fail_after
        self.last_messages: list[ChatMessage] = []

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        self.last_messages = list(messages)
        return self._generate()

    async def _generate(self) -> AsyncIterator[CompletionChunk]:
        for emitted, text in enumerate(self.chunks):
            if self.fail_after is not None and emitted >= self.fail_after:
                raise ProviderError("fake failure")
            yield CompletionChunk(delta=text)
        if self.fail_after is not None:
            raise ProviderError("fake failure")
        yield CompletionChunk(
            delta="",
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )

    async def healthcheck(self) -> None:
        return None


class FakeEmbedding:
    """Deterministic EmbeddingClient: sha256-seeded, L2-normalized pseudo-vectors.

    Same text -> same vector, across processes and runs. No semantics: only
    identical texts are similar (cosine 1.0), which is enough for tests.
    """

    def __init__(self, dimensions: int = 384) -> None:
        self.model = "intfloat/multilingual-e5-small"
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dimensions)]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    async def healthcheck(self) -> None:
        return None


_CANDIDATES_PER_LEG = 40  # matches Settings.retrieval_candidates default
_RRF_K = 60  # matches Settings.rrf_k default
_WORD_RE = re.compile(r"[a-z0-9]+")


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass(frozen=True, slots=True)
class _StoredChunk:
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    section: str | None
    page: int | None
    embedding: tuple[float, ...]
    order: int  # insertion order: deterministic tie-break


class InMemoryVectorStore:
    """Pure-Python VectorStore double mirroring PgVectorStore's RRF fusion.

    Vector leg: cosine similarity. FTS leg: naive keyword matching ranked by
    total query-term frequency. Each leg keeps its top 40 candidates; fusion
    is reciprocal rank fusion with rrf_k=60, like the SQL in store/pgvector.py.

    filenames: optional document_id -> filename mapping used to fill
    SearchHit.filename (add_chunks never sees filenames); defaults to
    "<document_id>.txt".
    """

    def __init__(self) -> None:
        self._chunks: list[_StoredChunk] = []
        self._counter = 0
        self.filenames: dict[UUID, str] = {}

    async def add_chunks(self, document_id: UUID, chunks: Sequence[ChunkIn]) -> None:
        for chunk in chunks:
            self._chunks.append(
                _StoredChunk(
                    chunk_id=uuid4(),
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    section=chunk.section,
                    page=chunk.page,
                    embedding=tuple(chunk.embedding),
                    order=self._counter,
                )
            )
            self._counter += 1

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        user_id: str,  # Phase 1: carried, not enforced -- mirrors PgVectorStore
        k: int = 8,
    ) -> list[SearchHit]:
        vec_ranks = self._vector_leg(query_embedding)
        fts_ranks = self._fts_leg(query_text)
        fused: list[tuple[float, _StoredChunk, int | None, int | None]] = []
        for chunk in self._chunks:
            vec_rank = vec_ranks.get(chunk.chunk_id)
            fts_rank = fts_ranks.get(chunk.chunk_id)
            if vec_rank is None and fts_rank is None:
                continue
            score = 0.0
            if vec_rank is not None:
                score += 1.0 / (_RRF_K + vec_rank)
            if fts_rank is not None:
                score += 1.0 / (_RRF_K + fts_rank)
            fused.append((score, chunk, vec_rank, fts_rank))
        fused.sort(key=lambda item: (-item[0], item[1].order))
        return [
            SearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=self.filenames.get(chunk.document_id, f"{chunk.document_id}.txt"),
                section=chunk.section,
                page=chunk.page,
                content=chunk.content,
                score=score,
                vec_rank=vec_rank,
                fts_rank=fts_rank,
            )
            for score, chunk, vec_rank, fts_rank in fused[:k]
        ]

    def _vector_leg(self, query_embedding: Sequence[float]) -> dict[UUID, int]:
        ranked = sorted(
            self._chunks,
            key=lambda chunk: (-_cosine(chunk.embedding, query_embedding), chunk.order),
        )
        top = ranked[:_CANDIDATES_PER_LEG]
        return {chunk.chunk_id: rank for rank, chunk in enumerate(top, start=1)}

    def _fts_leg(self, query_text: str) -> dict[UUID, int]:
        terms = set(_WORD_RE.findall(query_text.lower()))
        if not terms:
            return {}
        matches: list[tuple[int, _StoredChunk]] = []
        for chunk in self._chunks:
            tokens = _WORD_RE.findall(chunk.content.lower())
            frequency = sum(1 for token in tokens if token in terms)
            if frequency > 0:
                matches.append((frequency, chunk))
        matches.sort(key=lambda item: (-item[0], item[1].order))
        top = matches[:_CANDIDATES_PER_LEG]
        return {chunk.chunk_id: rank for rank, (_, chunk) in enumerate(top, start=1)}

    async def delete_document(self, document_id: UUID) -> None:
        self._chunks = [c for c in self._chunks if c.document_id != document_id]
        self.filenames.pop(document_id, None)

    async def healthcheck(self) -> None:
        return None


class FakeCursor:
    """Cursor stand-in: serves the canned rows given to FakePool."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class FakeConnection:
    """Connection stand-in: records executed SQL, answers with a FakeCursor."""

    def __init__(self, rows: list[tuple[object, ...]], executed: list[str]) -> None:
        self._rows = rows
        self._executed = executed

    async def execute(self, query: str, params: object = None) -> FakeCursor:
        self._executed.append(query)
        return FakeCursor(self._rows)


class FakePool:
    """Minimal AsyncConnectionPool stand-in for pure-unit boot tests.

    Deliberately NOT an AsyncConnectionPool instance: the lifespan in main.py
    detects that and skips every boot-time database step (migrations,
    embedding guard, sweep, demo seed), so tests can boot the full app without
    Postgres. Runtime queries (e.g. the /readyz ``SELECT 1``) succeed and
    return the canned ``rows``. Inject it into create_app with
    ``cast(AsyncConnectionPool, FakePool())``.
    """

    def __init__(self, rows: Sequence[tuple[object, ...]] = ()) -> None:
        self._rows = list(rows)
        self.executed: list[str] = []

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[FakeConnection]:
        yield FakeConnection(self._rows, self.executed)

    async def open(self, wait: bool = True, timeout: float = 30.0) -> None:
        return

    async def close(self) -> None:
        return
