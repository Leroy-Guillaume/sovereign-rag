"""psycopg3 async connection pool and the SQL migration runner.

Boot order (enforced by every caller): create_pool() -> apply_migrations()
-> pool.open(). The pool's configure hook registers the pgvector adapters,
which requires the vector extension created by 0001_schema.sql -- so no
pooled connection may exist before the migrations ran. apply_migrations
therefore opens its own dedicated connection.

The hook deliberately leaves row_factory alone: pooled connections yield
psycopg's default tuple rows (which is also how they are statically typed).
Callers that want mappings open an explicit cursor(row_factory=dict_row).
"""

from pathlib import Path
from typing import Any, LiteralString, cast

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from .config import Settings
from .errors import ConfigError

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

MIGRATION_LOCK_KEY = 745227  # arbitrary app-wide advisory lock id for migrations


async def _configure(conn: AsyncConnection[Any]) -> None:
    """Configure each new pooled connection: register the pgvector adapters.

    row_factory is left at psycopg's default (tuple rows) on purpose -- every
    caller that needs mappings opens conn.cursor(row_factory=dict_row).

    The pool requires this hook to leave the connection IDLE, hence the
    commit (TypeInfo.fetch inside register_vector_async opens a transaction).
    """
    await register_vector_async(conn)
    await conn.commit()


def create_pool(settings: Settings) -> AsyncConnectionPool:
    """Build the application pool. Deliberately NOT opened here."""
    return AsyncConnectionPool(
        settings.database_url,
        open=False,
        configure=_configure,
    )


async def apply_migrations(pool: AsyncConnectionPool) -> None:
    """Apply pending migrations/*.sql files in lexicographic order.

    Bookkeeping lives in schema_migrations; a session-level advisory lock
    serializes concurrent boots; each migration file runs in its own
    transaction, so a failing file leaves the database at the previous
    migration exactly.
    """
    conninfo = pool.conninfo
    if not isinstance(conninfo, str):  # pragma: no cover - create_pool always passes a str
        raise ConfigError("apply_migrations requires a pool built from a conninfo string")
    conn = await AsyncConnection.connect(conninfo, autocommit=True)
    try:
        await conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "filename text PRIMARY KEY, "
                "applied_at timestamptz DEFAULT now())"
            )
            cursor = await conn.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in await cursor.fetchall()}
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if sql_file.name in applied:
                    continue
                # Trusted first-party SQL shipped with the app -- the cast only
                # satisfies psycopg's LiteralString query typing.
                statements = cast(LiteralString, sql_file.read_text(encoding="utf-8"))
                async with conn.transaction():
                    await conn.execute(statements)
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s)",
                        (sql_file.name,),
                    )
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    finally:
        await conn.close()
