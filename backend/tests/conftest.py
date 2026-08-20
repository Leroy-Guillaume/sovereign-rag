"""Shared pytest fixtures: integration Postgres pool and in-process API client factory."""

import asyncio
import importlib
import os
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from fakes import make_settings
from sovereign_rag.config import Settings
from sovereign_rag.db import apply_migrations, create_pool
from sovereign_rag.embeddings.base import EmbeddingClient
from sovereign_rag.llm.base import LLMClient
from sovereign_rag.store.base import VectorStore

if sys.platform == "win32":  # psycopg async requires a selector loop on Windows
    # The policy API is deprecated from Python 3.14; this project pins 3.12.
    policy = asyncio.WindowsSelectorEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)  # pyright: ignore[reportDeprecated]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

_TRUNCATE_SQL = "TRUNCATE embedding_config, documents, chunks, conversations, messages CASCADE"

_migrations_applied = False


@pytest.fixture
async def pg(request: pytest.FixtureRequest) -> AsyncIterator[AsyncConnectionPool]:
    """Opened, migrated pool against TEST_DATABASE_URL; tables truncated per test.

    Skips the requesting test when the database is unreachable. Migrations are
    applied once per session (they are idempotent anyway). Test modules using
    this fixture must also set `pytestmark = pytest.mark.integration`.
    """
    global _migrations_applied
    request.applymarker(pytest.mark.integration)
    try:
        probe = await psycopg.AsyncConnection.connect(TEST_DATABASE_URL, connect_timeout=2)
        await probe.close()
    except psycopg.OperationalError:
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}")
    pool = create_pool(make_settings(database_url=TEST_DATABASE_URL))
    if not _migrations_applied:
        await apply_migrations(pool)
        _migrations_applied = True
    await pool.open(wait=True)
    async with pool.connection() as conn:
        await conn.execute(_TRUNCATE_SQL)
        # The frequency-band statistics must match the (now empty) tables:
        # a stale snapshot left by another test's refresh would ban terms of
        # this test's corpus and silence the lexical leg non-deterministically.
        await conn.execute("REFRESH MATERIALIZED VIEW lexeme_df")
    try:
        yield pool
    finally:
        await pool.close()


@asynccontextmanager
async def lifespan_client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    """Drive the app lifespan manually and yield an in-process HTTP client.

    httpx's ASGITransport never runs startup/shutdown; entering the router's
    lifespan context reproduces what uvicorn does, without extra dependencies.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


MakeClient = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def api_client() -> MakeClient:
    """Factory for in-process API clients with injected fakes.

    Usage: `async with api_client(settings=..., llm=FakeLLM()) as client: ...`
    Injected values win over factory-built ones inside create_app.
    """

    def make_client(
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        embedder: EmbeddingClient | None = None,
        store: VectorStore | None = None,
    ) -> AbstractAsyncContextManager[httpx.AsyncClient]:
        # main.py lands in a later task; resolve it at call time so that
        # importing this conftest never depends on it.
        main = importlib.import_module("sovereign_rag.main")
        app: FastAPI = main.create_app(
            settings if settings is not None else make_settings(),
            llm=llm,
            embedder=embedder,
            store=store,
        )
        return lifespan_client(app)

    return make_client
