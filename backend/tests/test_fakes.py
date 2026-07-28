"""Unit tests for the shared test doubles (fakes.py) and the conftest lifespan helper."""

import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI

from conftest import lifespan_client
from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings
from sovereign_rag.embeddings.base import EmbeddingClient
from sovereign_rag.errors import ProviderError
from sovereign_rag.llm.base import ChatMessage, LLMClient, collect
from sovereign_rag.store.base import ChunkIn, VectorStore


def test_make_settings_contract_defaults() -> None:
    settings = make_settings()
    assert settings.auth_api_keys == {
        "test-key-alice": "alice",
        "test-key-bob": "bob",
        "test-key-admin": "admin",
    }
    assert settings.auth_admin_users == {"admin"}
    assert settings.seed_demo_data is False
    assert make_settings(retrieval_top_k=3).retrieval_top_k == 3


async def test_fake_embedding_is_deterministic() -> None:
    first = FakeEmbedding()
    second = FakeEmbedding()
    assert await first.embed_query("hello world") == await second.embed_query("hello world")
    documents = await first.embed_documents(["hello world", "another text"])
    assert documents[0] == await first.embed_query("hello world")
    assert documents[0] != documents[1]


async def test_fake_embedding_vectors_are_normalized() -> None:
    vector = await FakeEmbedding().embed_query("normalize me")
    norm = math.sqrt(sum(x * x for x in vector))
    assert norm == pytest.approx(1.0, abs=1e-9)


async def test_fake_embedding_honors_dimensions() -> None:
    assert len(await FakeEmbedding().embed_query("x")) == 384
    small = FakeEmbedding(dimensions=8)
    assert small.dimensions == 8
    assert len(await small.embed_query("x")) == 8


async def test_fake_llm_yields_chunks_then_usage() -> None:
    llm = FakeLLM(chunks=["Hel", "lo"], prompt_tokens=7, completion_tokens=3)
    received = [chunk async for chunk in llm.stream_chat([ChatMessage(role="user", content="hi")])]
    assert [chunk.delta for chunk in received] == ["Hel", "lo", ""]
    assert received[-1].prompt_tokens == 7
    assert received[-1].completion_tokens == 3
    assert all(chunk.prompt_tokens is None for chunk in received[:-1])


def test_fake_llm_records_last_messages() -> None:
    llm = FakeLLM()
    messages = [
        ChatMessage(role="system", content="be brief"),
        ChatMessage(role="user", content="hi"),
    ]
    _ = llm.stream_chat(messages)  # recording happens at call time, before iteration
    assert llm.last_messages == messages


async def test_fake_llm_fail_after_raises_mid_stream() -> None:
    llm = FakeLLM(chunks=["a", "b", "c"], fail_after=2)
    received: list[str] = []
    with pytest.raises(ProviderError, match="fake failure"):
        async for chunk in llm.stream_chat([ChatMessage(role="user", content="hi")]):
            received.append(chunk.delta)
    assert received == ["a", "b"]


async def test_collect_drains_stream_and_returns_usage() -> None:
    llm = FakeLLM(chunks=["Hel", "lo"], prompt_tokens=7, completion_tokens=3)
    text, prompt_tokens, completion_tokens = await collect(
        llm.stream_chat([ChatMessage(role="user", content="hi")])
    )
    assert text == "Hello"
    assert prompt_tokens == 7
    assert completion_tokens == 3


async def test_hit_in_both_legs_outranks_single_leg_hits() -> None:
    store = InMemoryVectorStore()
    document_id = uuid4()
    await store.add_chunks(
        document_id,
        [
            ChunkIn(chunk_index=0, content="alpha appears here", embedding=[1.0, 0.0]),
            ChunkIn(chunk_index=1, content="nothing relevant", embedding=[0.95, 0.312]),
            ChunkIn(chunk_index=2, content="alpha alpha alpha", embedding=[-1.0, 0.0]),
        ],
    )
    hits = await store.hybrid_search("alpha", [1.0, 0.0], user_id="alice", k=8)
    # Vector leg: sims 1.0 / 0.95 / -1.0 -> ranks 1, 2, 3.
    # FTS leg: term frequency 3 for "alpha alpha alpha" (rank 1), 1 for chunk 0 (rank 2).
    assert [hit.content for hit in hits] == [
        "alpha appears here",
        "alpha alpha alpha",
        "nothing relevant",
    ]
    assert hits[0].vec_rank == 1
    assert hits[0].fts_rank == 2
    assert hits[0].score == pytest.approx(1 / 61 + 1 / 62)
    vec_only = hits[2]
    assert vec_only.fts_rank is None
    assert vec_only.score == pytest.approx(1 / 62)


async def test_leg_exclusive_hits_have_none_ranks() -> None:
    store = InMemoryVectorStore()
    document_id = uuid4()
    fillers = [
        ChunkIn(chunk_index=i, content=f"filler number {i}", embedding=[1.0, 0.0])
        for i in range(40)
    ]
    keyword_only = ChunkIn(chunk_index=40, content="alpha", embedding=[-1.0, 0.0])
    await store.add_chunks(document_id, [*fillers, keyword_only])
    hits = await store.hybrid_search("alpha", [1.0, 0.0], user_id="alice", k=41)
    # "alpha" ranks 41st on the vector leg -> outside the 40-candidate window.
    alpha_hit = next(hit for hit in hits if hit.content == "alpha")
    assert alpha_hit.vec_rank is None
    assert alpha_hit.fts_rank == 1
    filler_hit = next(hit for hit in hits if hit.content.startswith("filler"))
    assert filler_hit.vec_rank is not None
    assert filler_hit.fts_rank is None


async def test_hybrid_search_respects_k() -> None:
    store = InMemoryVectorStore()
    document_id = uuid4()
    await store.add_chunks(
        document_id,
        [ChunkIn(chunk_index=i, content=f"chunk {i}", embedding=[1.0, 0.0]) for i in range(10)],
    )
    hits = await store.hybrid_search("chunk", [1.0, 0.0], user_id="alice", k=3)
    assert len(hits) == 3


async def test_delete_document_removes_its_chunks() -> None:
    store = InMemoryVectorStore()
    doc_a, doc_b = uuid4(), uuid4()
    await store.add_chunks(
        doc_a, [ChunkIn(chunk_index=0, content="shared term", embedding=[1.0, 0.0])]
    )
    await store.add_chunks(
        doc_b, [ChunkIn(chunk_index=0, content="shared term too", embedding=[1.0, 0.0])]
    )
    await store.delete_document(doc_a)
    hits = await store.hybrid_search("shared", [1.0, 0.0], user_id="alice", k=8)
    assert hits
    assert {hit.document_id for hit in hits} == {doc_b}


async def test_fakes_satisfy_protocols() -> None:
    # The three assignments are type-checked by pyright: structural conformance.
    llm: LLMClient = FakeLLM()
    embedder: EmbeddingClient = FakeEmbedding()
    store: VectorStore = InMemoryVectorStore()
    await llm.healthcheck()
    await embedder.healthcheck()
    await store.healthcheck()
    assert llm.model == "fake/fake"
    assert embedder.model == "intfloat/multilingual-e5-small"


async def test_lifespan_client_drives_startup_and_shutdown() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    @app.get("/ping")
    async def ping() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    async with lifespan_client(app) as client:
        assert events == ["startup"]
        response = await client.get("/ping")
    assert response.status_code == 200
    assert events == ["startup", "shutdown"]
