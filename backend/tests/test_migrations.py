"""Integration tests for the schema migration runner and the connection pool.

These tests need a live Postgres with the pgvector extension available
(TEST_DATABASE_URL, default postgresql://rag:rag@localhost:5432/rag_test).
They skip cleanly when the database is unreachable.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from pgvector import Vector
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sovereign_rag.config import Settings
from sovereign_rag.db import apply_migrations, create_pool

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)


def _settings(**overrides: Any) -> Settings:
    """Build Settings without reading .env (pyright cannot see BaseSettings' _env_file)."""
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]


@pytest.fixture
async def migrated_pool() -> AsyncIterator[AsyncConnectionPool]:
    """Opened pool against the test database, migrations applied."""
    try:
        probe = await psycopg.AsyncConnection.connect(TEST_DATABASE_URL, connect_timeout=2)
        await probe.close()
    except psycopg.OperationalError:
        pytest.skip(f"Postgres not reachable at {TEST_DATABASE_URL}")
    settings = _settings(database_url=TEST_DATABASE_URL)
    pool = create_pool(settings)
    await apply_migrations(pool)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


def test_optional_migrations_are_never_picked_up() -> None:
    """migrations/optional/ holds operator-applied upgrades; the runner's glob
    is non-recursive by design, so nothing under a subdirectory may ever run
    unattended. This pins that contract against a future glob change."""
    from sovereign_rag.db import MIGRATIONS_DIR

    optional = MIGRATIONS_DIR / "optional"
    assert optional.is_dir(), "the shipped optional upgrade directory must exist"
    assert any(optional.glob("*.sql")), "it must actually ship at least one upgrade"
    picked = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    assert not {path.name for path in optional.glob("*.sql")} & picked


async def test_apply_migrations_twice_is_idempotent(
    migrated_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(migrated_pool)  # second application (fixture already ran one)
    async with migrated_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
        rows = await cur.fetchall()
    assert [row["filename"] for row in rows] == [
        "0001_schema.sql",
        "0002_lexeme_df.sql",
        "0003_document_permissions.sql",
    ]


async def test_vector_extension_installed(migrated_pool: AsyncConnectionPool) -> None:
    async with migrated_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT count(*) AS n FROM pg_extension WHERE extname = 'vector'")
        row = await cur.fetchone()
    assert row is not None
    assert row["n"] == 1


async def test_all_phase1_tables_exist(migrated_pool: AsyncConnectionPool) -> None:
    expected = {"embedding_config", "documents", "chunks", "conversations", "messages"}
    async with migrated_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row["tablename"] for row in await cur.fetchall()}
    assert expected <= tables


async def test_chunks_embedding_dimension_is_384(migrated_pool: AsyncConnectionPool) -> None:
    async with migrated_pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT format_type(atttypid, atttypmod) AS coltype FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row["coltype"] == "vector(384)"


async def test_pooled_connections_have_vector_registered(
    migrated_pool: AsyncConnectionPool,
) -> None:
    """The configure hook must register the pgvector adapters on every connection.

    It must NOT change row_factory: pooled connections keep psycopg's default
    tuple rows; dict rows are opt-in per cursor (row_factory=dict_row).
    """
    sha = uuid4().hex  # unique per run: documents.sha256 has a UNIQUE constraint
    async with migrated_pool.connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO documents (filename, content_type, sha256, size_bytes, owner_id) "
            "VALUES (%s, 'txt', %s, 5, 'alice') RETURNING id",
            ("probe.txt", sha),
        )
        doc_row = await cursor.fetchone()  # tuple row: the pool never sets dict_row
        assert doc_row is not None
        document_id = doc_row[0]
        await conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content, embedding) "
            "VALUES (%s, 0, 'hello', %s)",
            (document_id, Vector([0.5] * 384)),
        )
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT embedding FROM chunks WHERE document_id = %s", (document_id,))
            chunk_row = await cur.fetchone()  # explicit opt-in to dict rows
    assert chunk_row is not None
    stored = chunk_row["embedding"]
    values = stored.to_list() if hasattr(stored, "to_list") else list(stored)
    assert len(values) == 384
