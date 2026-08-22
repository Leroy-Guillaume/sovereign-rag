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
    assert body["unanswered"] == []


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


async def test_metrics_window_excludes_old_messages(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    """The 30-day window is delivered behavior: a message just outside it
    must not count anywhere (usage, latency, citations)."""
    async with pg.connection() as conn:
        conv = uuid4()
        await conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, 'alice', 't')",
            (conv,),
        )
        await conn.execute(
            """INSERT INTO messages
               (conversation_id, request_id, role, content, sources,
                prompt_tokens, completion_tokens, retrieval_ms, generation_ms,
                error_code, created_at)
               VALUES (%s, %s, 'assistant', 'x', %s, 10, 5, 100, 1000, NULL,
                       now() - interval '31 days')""",
            (conv, uuid4(), Jsonb([{"filename": "old.md"}])),
        )
    async with _client(api_client) as client:
        body = (await client.get("/api/admin/metrics", headers=AUTH_ADMIN)).json()
    assert body["answers"] == 0
    assert body["prompt_tokens"] == 0
    assert body["retrieval"] == {"p50_ms": None, "p95_ms": None}
    assert body["top_cited"] == []


async def test_metrics_days_parameter_widens_the_window(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    """?days= lets the dashboard switch between 7/30/90-day views: a 31-day-old
    answer is outside the default window but inside days=90."""
    async with pg.connection() as conn:
        conv = uuid4()
        await conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, 'alice', 't')",
            (conv,),
        )
        await conn.execute(
            """INSERT INTO messages
               (conversation_id, request_id, role, content, sources,
                prompt_tokens, completion_tokens, retrieval_ms, generation_ms,
                error_code, created_at)
               VALUES (%s, %s, 'assistant', 'x', %s, 10, 5, 100, 1000, NULL,
                       now() - interval '31 days')""",
            (conv, uuid4(), Jsonb([{"filename": "old.md"}])),
        )
    async with _client(api_client) as client:
        body = (await client.get("/api/admin/metrics?days=90", headers=AUTH_ADMIN)).json()
        assert body["window_days"] == 90
        assert body["answers"] == 1
        assert body["top_cited"] == [{"filename": "old.md", "citations": 1}]
        # Bounds are enforced, not silently clamped.
        for bad in ("0", "366"):
            bad_response = await client.get(f"/api/admin/metrics?days={bad}", headers=AUTH_ADMIN)
            assert bad_response.status_code == 422


async def test_metrics_lists_unanswered_questions(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    """Clean zero-source answers aggregate back to their user question,
    case/whitespace-insensitively; provider failures and sourced answers
    stay out."""
    async with pg.connection() as conn:
        conv = uuid4()
        await conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (%s, 'alice', 't')",
            (conv,),
        )
        turns: list[tuple[str, str, list[dict[str, str]], str | None]] = [
            # (role, content, sources, error_code)
            ("user", "Sanctions eIDAS registre foncier ?", [], None),
            ("assistant", "Le corpus ne couvre pas ce point.", [], None),
            ("user", "  sanctions EIDAS registre foncier ?", [], None),
            ("assistant", "Toujours rien dans le corpus.", [], None),
            ("user", "Question avec reponse", [], None),
            ("assistant", "Reponse sourcee [1]", [{"filename": "a.md"}], None),
            ("user", "Question tombee en erreur", [], None),
            ("assistant", "", [], "provider_error"),
        ]
        # Distinct timestamps per turn, as in production (one transaction per
        # message); a single test transaction would freeze now() and make the
        # question/answer pairing ambiguous.
        for index, (role, content, sources, err) in enumerate(turns):
            await conn.execute(
                """INSERT INTO messages
                   (conversation_id, request_id, role, content, sources, error_code,
                    created_at)
                   VALUES (%s, %s, %s, %s, %s, %s,
                           now() - interval '1 hour' + make_interval(secs => %s))""",
                (conv, uuid4(), role, content, Jsonb(sources), err, index),
            )
    async with _client(api_client) as client:
        body = (await client.get("/api/admin/metrics", headers=AUTH_ADMIN)).json()
    assert len(body["unanswered"]) == 1
    entry = body["unanswered"][0]
    assert entry["occurrences"] == 2
    # The most recent phrasing represents the case-insensitive group.
    assert entry["question"].strip().lower() == "sanctions eidas registre foncier ?"
