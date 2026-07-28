"""Composition root tests: wiring, middleware, exception mapping, boot guards."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from psycopg_pool import AsyncConnectionPool

from fakes import FakeEmbedding, FakeLLM, FakePool, InMemoryVectorStore, make_settings
from sovereign_rag.errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    ProviderError,
    SovereignRagError,
)
from sovereign_rag.main import create_app


@asynccontextmanager
async def booted_client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    """Drive the app lifespan manually (ASGITransport does not) and yield a client."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def make_unit_app() -> FastAPI:
    """App wired with fakes only: the lifespan boots without Postgres (FakePool)."""
    return create_app(
        make_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        pool=cast(AsyncConnectionPool, FakePool()),
    )


async def test_app_boots_with_fakes() -> None:
    app = make_unit_app()
    async with booted_client(app) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_request_id_header_present_and_unique() -> None:
    app = make_unit_app()
    async with booted_client(app) as client:
        first = await client.get("/healthz")
        second = await client.get("/healthz")
    rid1 = first.headers["x-request-id"]
    rid2 = second.headers["x-request-id"]
    uuid.UUID(rid1)  # raises ValueError if the header is not a valid UUID
    uuid.UUID(rid2)
    assert rid1 != rid2


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_detail"),
    [
        (AuthError("bad key"), 401, "bad key"),
        (ExtractionError("no extractable text"), 422, "no extractable text"),
        (ProviderError("llm unreachable"), 502, "llm unreachable"),
        (ConfigError("secret dsn leaked"), 500, "server misconfiguration, check logs"),
    ],
)
async def test_exception_handler_mapping(
    exc: SovereignRagError, expected_status: int, expected_detail: str
) -> None:
    app = make_unit_app()

    @app.get("/boom")
    async def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise exc

    async with booted_client(app) as client:
        response = await client.get("/boom")
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


@pytest.mark.integration
async def test_boot_applies_guard_and_inserts_embedding_config(
    pg: AsyncConnectionPool,
) -> None:
    settings = make_settings()
    app = create_app(
        settings,
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        pool=pg,
    )
    async with app.router.lifespan_context(app):
        pass
    async with pg.connection() as conn:
        cursor = await conn.execute("SELECT model, dimensions FROM embedding_config")
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == settings.embedding_model
    assert row[1] == settings.embedding_dimensions


@pytest.mark.integration
async def test_second_boot_with_changed_embedding_model_refuses_to_start(
    pg: AsyncConnectionPool,
) -> None:
    first = create_app(
        make_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        pool=pg,
    )
    async with first.router.lifespan_context(first):
        pass
    changed = make_settings(embedding_model="BAAI/bge-m3", embedding_dimensions=1024)
    second = create_app(
        changed,
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        pool=pg,
    )
    with pytest.raises(RuntimeError, match="Embedding model mismatch"):
        async with second.router.lifespan_context(second):
            pass


@pytest.mark.integration
async def test_interrupted_ingestions_swept_to_failed_at_boot(
    pg: AsyncConnectionPool,
) -> None:
    async with pg.connection() as conn:
        await conn.execute(
            "INSERT INTO documents (filename, content_type, sha256, size_bytes, status, owner_id)"
            " VALUES ('stuck.pdf', 'pdf', 'cafebabe', 123, 'processing', 'alice')"
        )
    app = create_app(
        make_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
        pool=pg,
    )
    async with app.router.lifespan_context(app):
        pass
    async with pg.connection() as conn:
        cursor = await conn.execute("SELECT status, error FROM documents WHERE sha256 = 'cafebabe'")
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "interrupted by restart"
