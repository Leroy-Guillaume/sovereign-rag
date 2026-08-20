"""Admin metrics endpoint: authorization, empty state, aggregates."""

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import uuid4

import httpx
import pytest
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}
AUTH_ADMIN = {"Authorization": "Bearer test-key-admin"}

pytestmark = pytest.mark.integration


def _client(api_client: ClientFactory) -> AbstractAsyncContextManager[httpx.AsyncClient]:
    return api_client(
        settings=make_settings(database_url=TEST_DATABASE_URL),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    )


async def _seed_messages(pg: AsyncConnectionPool) -> None:
    """Two conversations, three answers with known metrics, one mid-stream error."""
    async with pg.connection() as conn:
        convs = [uuid4(), uuid4()]
        for conv in convs:
            await conn.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES (%s, 'alice', 't')",
                (conv,),
            )
        rows = [
            # conversation, retrieval_ms, generation_ms, prompt, completion, error, sources
            (convs[0], 100, 1000, 10, 5, None, [{"filename": "a.md"}, {"filename": "b.md"}]),
            (convs[0], 200, 2000, 20, 10, None, [{"filename": "a.md"}]),
            (convs[1], 300, 3000, 30, 15, "provider_error", [{"filename": "c.md"}]),
        ]
        for conv, ret, gen, pt, ct, err, sources in rows:
            await conn.execute(
                """INSERT INTO messages
                   (conversation_id, request_id, role, content, sources,
                    prompt_tokens, completion_tokens, retrieval_ms, generation_ms, error_code)
                   VALUES (%s, %s, 'assistant', 'x', %s, %s, %s, %s, %s, %s)""",
                (conv, uuid4(), Jsonb(sources), pt, ct, ret, gen, err),
            )


async def test_metrics_requires_admin(api_client: ClientFactory, pg: Any) -> None:
    async with _client(api_client) as client:
        assert (await client.get("/api/admin/metrics", headers=AUTH_ALICE)).status_code == 403
        assert (await client.get("/api/admin/metrics")).status_code == 401


async def test_metrics_empty_database_returns_zeros(api_client: ClientFactory, pg: Any) -> None:
    async with _client(api_client) as client:
        body = (await client.get("/api/admin/metrics", headers=AUTH_ADMIN)).json()
    assert body["answers"] == 0
    assert body["conversations"] == 0
    assert body["errors"] == 0
    assert body["retrieval"] == {"p50_ms": None, "p95_ms": None}
    assert body["top_cited"] == []


async def test_metrics_aggregates_the_typed_columns(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    await _seed_messages(pg)
    async with _client(api_client) as client:
        body = (await client.get("/api/admin/metrics", headers=AUTH_ADMIN)).json()

    assert body["window_days"] == 30
    assert body["answers"] == 3
    assert body["conversations"] == 2
    assert body["prompt_tokens"] == 60
    assert body["completion_tokens"] == 30
    assert body["errors"] == 1
    assert body["retrieval"] == {"p50_ms": 200, "p95_ms": 290}
    assert body["generation"] == {"p50_ms": 2000, "p95_ms": 2900}
    # citation ledger: a.md cited twice, ties broken by name
    assert body["top_cited"][0] == {"filename": "a.md", "citations": 2}
    assert {c["filename"] for c in body["top_cited"]} == {"a.md", "b.md", "c.md"}
