"""SSE chat endpoint tests: event protocol, prompt construction, persistence, isolation."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from fakes import FakeEmbedding, FakeLLM, FakeReranker, InMemoryVectorStore, make_settings
from sovereign_rag.auth import User
from sovereign_rag.chat.prompts import NO_CONTEXT_INSTRUCTION, build_messages, hits_to_sources
from sovereign_rag.chat.service import ChatEvent, ChatService
from sovereign_rag.llm.base import ChatMessage, CompletionChunk
from sovereign_rag.store.base import ChunkIn, SearchHit

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}
AUTH_BOB = {"Authorization": "Bearer test-key-bob"}
AUTH_ADMIN = {"Authorization": "Bearer test-key-admin"}

CORPUS = [
    "The nLPD is the revised Swiss federal act on data protection.",
    "LIPAD governs transparency and data protection in the canton of Geneva.",
]


def parse_sse(raw: str) -> list[tuple[str, Any]]:
    """Decode an SSE payload into (event, parsed-json-data) pairs, ignoring ping comments."""
    events: list[tuple[str, Any]] = []
    for frame in raw.split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        name = ""
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        if name:
            events.append((name, json.loads(data)))
    return events


def _hit(
    content: str,
    *,
    filename: str = "doc.md",
    section: str | None = None,
    page: int | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=filename,
        section=section,
        page=page,
        content=content,
        score=0.03,
        vec_rank=1,
        fts_rank=None,
    )


async def seeded_store(embedder: FakeEmbedding) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    embeddings = await embedder.embed_documents(CORPUS)
    await store.add_chunks(
        uuid4(),
        [
            ChunkIn(chunk_index=i, content=text, embedding=emb)
            for i, (text, emb) in enumerate(zip(CORPUS, embeddings, strict=True))
        ],
    )
    return store


# --- prompt construction (pure, no DB) ---------------------------------------------------


def test_build_messages_numbers_context_and_applies_redact() -> None:
    hits = [_hit("alpha", filename="a.md", section="Intro"), _hit("beta", filename="b.pdf", page=3)]
    history = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="yo")]
    messages = build_messages(history, "what?", hits, redact=lambda text: text.upper())
    assert messages[0].role == "system"
    assert "[1] a.md - Intro:\nALPHA" in messages[0].content
    assert "[2] b.pdf - page 3:\nBETA" in messages[0].content
    assert messages[1:3] == history
    assert messages[-1] == ChatMessage(role="user", content="what?")


def test_build_messages_zero_hits_appends_no_context_instruction() -> None:
    messages = build_messages([], "anything?", [])
    assert messages[0].role == "system"
    assert NO_CONTEXT_INSTRUCTION in messages[0].content
    assert messages[-1] == ChatMessage(role="user", content="anything?")


def test_hits_to_sources_truncates_excerpt_to_500_chars() -> None:
    source = hits_to_sources([_hit("x" * 900)])[0]
    assert source["excerpt"] == "x" * 500
    assert UUID(source["chunk_id"])
    assert UUID(source["document_id"])
    assert source["vec_rank"] == 1
    assert source["fts_rank"] is None


# --- SSE protocol + persistence (integration: needs Postgres) ----------------------------


@pytest.mark.integration
async def test_chat_happy_path_streams_sources_and_deltas(
    api_client: ClientFactory, pg: object
) -> None:
    embedder = FakeEmbedding()
    store = await seeded_store(embedder)
    llm = FakeLLM(chunks=["The nLPD ", "is the Swiss data protection act [1]."])
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(settings=settings, llm=llm, embedder=embedder, store=store) as client:
        resp = await client.post(
            "/api/chat",
            json={"conversation_id": None, "message": "What is the nLPD?"},
            headers=AUTH_ALICE,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-store"
        assert resp.headers["x-accel-buffering"] == "no"

        events = parse_sse(resp.text)
        names = [name for name, _ in events]
        assert names == ["start", "sources", "delta", "delta", "done"]

        conversation_id = UUID(events[0][1]["conversation_id"])
        sources = events[1][1]
        assert len(sources) == 2
        assert {s["excerpt"] for s in sources} == set(CORPUS)
        assert {"chunk_id", "document_id", "filename", "section", "page"} <= sources[0].keys()
        assert {"excerpt", "score", "vec_rank", "fts_rank"} <= sources[0].keys()

        deltas = "".join(data["text"] for name, data in events if name == "delta")
        assert deltas == "The nLPD is the Swiss data protection act [1]."

        done = events[-1][1]
        assert UUID(done["message_id"])
        assert done["prompt_tokens"] == 10
        assert done["completion_tokens"] == 5
        assert isinstance(done["retrieval_ms"], int) and done["retrieval_ms"] >= 0
        assert isinstance(done["generation_ms"], int) and done["generation_ms"] >= 0

        detail = await client.get(f"/api/conversations/{conversation_id}", headers=AUTH_ALICE)
        assert detail.status_code == 200
        body = detail.json()
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
        assert body["messages"][1]["content"] == deltas
        assert body["messages"][1]["sources"]


@pytest.mark.integration
async def test_chat_zero_hits_sends_empty_sources_and_no_context_prompt(
    api_client: ClientFactory, pg: object
) -> None:
    llm = FakeLLM(chunks=["Nothing relevant was found."])
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(
        settings=settings, llm=llm, embedder=FakeEmbedding(), store=InMemoryVectorStore()
    ) as client:
        resp = await client.post(
            "/api/chat", json={"message": "Unknown topic?"}, headers=AUTH_ALICE
        )
        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert [name for name, _ in events] == ["start", "sources", "delta", "done"]
        assert events[1][1] == []
    assert llm.last_messages is not None
    assert llm.last_messages[0].role == "system"
    assert NO_CONTEXT_INSTRUCTION in llm.last_messages[0].content


@pytest.mark.integration
async def test_chat_provider_failure_persists_partial_answer(
    api_client: ClientFactory, pg: object
) -> None:
    embedder = FakeEmbedding()
    store = await seeded_store(embedder)
    llm = FakeLLM(chunks=["partial ", "never sent"], fail_after=1)
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(settings=settings, llm=llm, embedder=embedder, store=store) as client:
        resp = await client.post(
            "/api/chat", json={"message": "What is the nLPD?"}, headers=AUTH_ALICE
        )
        assert resp.status_code == 200
        events = parse_sse(resp.text)
        assert [name for name, _ in events] == ["start", "sources", "delta", "error"]
        assert events[-1][1]["code"] == "provider_error"

    async with await psycopg.AsyncConnection.connect(TEST_DATABASE_URL) as conn:
        cur = await conn.execute(
            "SELECT content, error_code FROM messages"
            " WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "partial "
    assert row[1] == "provider_error"


@pytest.mark.integration
async def test_foreign_conversation_is_404_and_lists_are_owner_scoped(
    api_client: ClientFactory, pg: object
) -> None:
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(
        settings=settings,
        llm=FakeLLM(chunks=["ok"]),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        resp = await client.post("/api/chat", json={"message": "hello there"}, headers=AUTH_ALICE)
        conversation_id = parse_sse(resp.text)[0][1]["conversation_id"]

        as_bob = await client.post(
            "/api/chat",
            json={"conversation_id": conversation_id, "message": "intrusion"},
            headers=AUTH_BOB,
        )
        assert as_bob.status_code == 404

        unknown = await client.post(
            "/api/chat",
            json={"conversation_id": str(uuid4()), "message": "ghost"},
            headers=AUTH_ALICE,
        )
        assert unknown.status_code == 404

        detail_as_bob = await client.get(f"/api/conversations/{conversation_id}", headers=AUTH_BOB)
        assert detail_as_bob.status_code == 404

        bob_list = await client.get("/api/conversations", headers=AUTH_BOB)
        assert bob_list.json() == []
        alice_list = await client.get("/api/conversations", headers=AUTH_ALICE)
        assert [c["id"] for c in alice_list.json()] == [conversation_id]


@pytest.mark.integration
async def test_conversation_title_is_first_60_chars(api_client: ClientFactory, pg: object) -> None:
    message = "Explain the difference between the nLPD and the GDPR in the Geneva context please"
    assert len(message) > 60
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(
        settings=settings,
        llm=FakeLLM(chunks=["ok"]),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        await client.post("/api/chat", json={"message": message}, headers=AUTH_ALICE)
        conversations = (await client.get("/api/conversations", headers=AUTH_ALICE)).json()
        assert len(conversations) == 1
        assert conversations[0]["title"] == message[:60]


# --- client disconnect (service-level, deterministic cancellation point) -----------------


class GatedLLM:
    """LLMClient double that yields one delta then parks until cancelled.

    The gate event is never set: the stream suspends on it deterministically,
    so the test can cancel the consumer exactly mid-generation without sleeps.
    """

    def __init__(self) -> None:
        self.model = "fake/gated"
        self.streaming = asyncio.Event()  # set once the first delta is out
        self._gate = asyncio.Event()  # never set: cancellation lands here

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        return self._generate()

    async def _generate(self) -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="partial ")
        self.streaming.set()
        await self._gate.wait()
        yield CompletionChunk(delta="never sent")  # pragma: no cover - cancelled before this

    async def healthcheck(self) -> None:
        return None


@pytest.mark.integration
async def test_reranker_widens_the_pool_and_reorders_sources(
    pg: AsyncConnectionPool,
) -> None:
    """With a reranker the fused query over-fetches RERANKER_CANDIDATES and the
    sources event carries the reranked order, trimmed back to top_k."""
    store = InMemoryVectorStore()
    embedder = FakeEmbedding()
    # one document per chunk: the in-memory per-document cap must not shrink
    # the pool this test is about
    for i in range(5):
        doc_id = uuid4()
        store.filenames[doc_id] = f"policy-{i}.md"
        content = f"nlpd rule {i}"
        await store.add_chunks(doc_id, [ChunkIn(0, content, await embedder.embed_query(content))])
    reranker = FakeReranker()
    service = ChatService(
        pool=pg,
        llm=FakeLLM(),
        embedder=embedder,
        store=store,
        settings=make_settings(
            database_url=TEST_DATABASE_URL,
            retrieval_top_k=2,
            reranker_candidates=4,
        ),
        reranker=reranker,
    )
    user = User(id="alice", roles=frozenset())

    events = [e async for e in service.stream_reply(user, None, "nlpd rule")]

    sources = cast(list[dict[str, Any]], next(e for e in events if e.type == "sources").data)
    assert len(sources) == 2, "reranked results must be trimmed back to top_k"
    [(query, pool, k)] = reranker.calls
    assert query == "nlpd rule"
    assert pool == 4, "the fused query must over-fetch reranker_candidates"
    assert k == 2
    fused = await store.hybrid_search(
        "nlpd rule", await embedder.embed_query("nlpd rule"), user_id="alice", k=4
    )
    assert [s["chunk_id"] for s in sources] == [str(h.chunk_id) for h in reversed(fused)][:2], (
        "sources must follow the reranker's order, not the fused order"
    )


@pytest.mark.integration
async def test_client_disconnect_persists_partial_answer_and_reraises(
    pg: AsyncConnectionPool,
    caplog: pytest.LogCaptureFixture,
    recwarn: pytest.WarningsRecorder,
) -> None:
    llm = GatedLLM()
    service = ChatService(
        pool=pg,
        llm=llm,
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        settings=make_settings(database_url=TEST_DATABASE_URL),
    )
    user = User(id="alice", roles=frozenset())
    received: list[ChatEvent] = []

    async def consume() -> None:
        async for event in service.stream_reply(user, None, "What is the nLPD?"):
            received.append(event)

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(llm.streaming.wait(), timeout=5)
    # anyio cancel scopes are level-triggered: cancellation is re-delivered at
    # every await until the task actually ends. Re-cancelling on every loop
    # tick reproduces that, so an unshielded INSERT in the persistence finally
    # would itself be cancelled and the audit row lost - this loop is what
    # makes the test discriminate the shielded fix from the pre-fix code.
    while not consumer.done():
        consumer.cancel()
        await asyncio.sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert [event.type for event in received] == ["start", "sources", "delta"]

    async with pg.connection() as conn:
        cur = await conn.execute(
            "SELECT content, error_code FROM messages WHERE role = 'assistant'"
        )
        rows = await cur.fetchall()
    assert rows == [("partial ", "client_disconnect")]

    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.integration
async def test_me_returns_identity_and_roles(api_client: ClientFactory, pg: object) -> None:
    settings = make_settings(database_url=TEST_DATABASE_URL)
    async with api_client(
        settings=settings, llm=FakeLLM(), embedder=FakeEmbedding(), store=InMemoryVectorStore()
    ) as client:
        me = await client.get("/api/me", headers=AUTH_ADMIN)
        assert me.status_code == 200
        assert me.json() == {"id": "admin", "roles": ["admin"]}
        alice = await client.get("/api/me", headers=AUTH_ALICE)
        assert alice.json() == {"id": "alice", "roles": []}
