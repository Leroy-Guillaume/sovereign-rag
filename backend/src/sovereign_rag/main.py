"""Application composition root.

Everything concrete is chosen here and only here: adapters are built via the
provider factories, stored on ``app.state`` and consumed by routes through
``request.app.state``. Tests inject fakes through ``create_app`` keyword
arguments; injected values always win over factory-built ones.

Boot sequence (lifespan): create pool -> apply migrations -> open pool ->
embedding guard -> sweep interrupted ingestions -> build adapters -> warmup ->
services -> demo seed. Migrations run BEFORE the pool is opened because the
pool's configure hook registers the pgvector type adapters, which requires the
`vector` extension that 0001_schema.sql creates -- opening first would break
every boot against a fresh database. Boot-time database steps only run against
a real AsyncConnectionPool, so pure-unit tests can inject a FakePool and boot
without Postgres. A failed boot closes the pool it created; a clean shutdown
drains in-flight ingestion tasks before closing it.
"""

import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from structlog.typing import Processor

from .auth import ApiKeyAuth
from .chat.service import ChatService
from .config import Settings
from .db import apply_migrations, create_pool
from .embeddings import get_embedding_client
from .embeddings.base import EmbeddingClient
from .errors import AuthError, ConfigError, ExtractionError, ProviderError
from .ingestion.service import IngestionService
from .llm import get_llm_client
from .llm.base import LLMClient
from .reranking import get_reranker
from .routes import admin as admin_routes
from .routes import chat as chat_routes
from .routes import documents as documents_routes
from .routes import health as health_routes
from .store import get_vector_store
from .store.base import VectorStore

logger = structlog.get_logger("sovereign_rag")


def _configure_logging(settings: Settings) -> None:
    """JSON logs in prod, pretty console logs in dev; request_id via contextvars."""
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.app_env == "prod"
        else structlog.dev.ConsoleRenderer()
    )
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def _is_real_pool(pool: object) -> bool:
    """True for a real psycopg pool; the tests' FakePool returns False."""
    return isinstance(pool, AsyncConnectionPool)


async def _ensure_embedding_config(pool: AsyncConnectionPool, settings: Settings) -> None:
    """Boot guard against the worst RAG failure mode: a silently invalid index."""
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT model, dimensions FROM embedding_config")
        row = await cursor.fetchone()
        if row is None:
            await conn.execute(
                "INSERT INTO embedding_config (model, dimensions) VALUES (%s, %s)",
                (settings.embedding_model, settings.embedding_dimensions),
            )
            return
        db_model, db_dim = row[0], row[1]
        if db_model != settings.embedding_model or db_dim != settings.embedding_dimensions:
            raise RuntimeError(
                f"Embedding model mismatch: index built with {db_model} ({db_dim} dims), "
                f"configured {settings.embedding_model} "
                f"({settings.embedding_dimensions} dims). "
                "Changing embedding models invalidates the whole index. See README."
            )


async def _sweep_interrupted_documents(pool: AsyncConnectionPool) -> None:
    """Ingestion runs in-process: a restart kills in-flight jobs; mark them failed."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE documents SET status = 'failed', error = 'interrupted by restart' "
            "WHERE status = 'processing'"
        )


async def _documents_table_empty(pool: AsyncConnectionPool) -> bool:
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT EXISTS (SELECT 1 FROM documents)")
        row = await cursor.fetchone()
    return row is not None and not row[0]


def _resolve_demo_dir(settings: Settings) -> Path:
    """Resolve the demo corpus directory.

    Relative values (default ``../data/demo``) resolve against ``backend/``,
    i.e. the directory containing ``src/``. In the Docker image (project under
    /app) this yields /data/demo; compose mounts the repo's data/demo there or
    sets DEMO_DATA_DIR to an absolute path.
    """
    demo_dir = Path(settings.demo_data_dir)
    if demo_dir.is_absolute():
        return demo_dir
    backend_dir = Path(__file__).resolve().parents[2]
    return (backend_dir / demo_dir).resolve()


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def handle_auth_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: AuthError
    ) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=401)

    @app.exception_handler(ExtractionError)
    async def handle_extraction_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ExtractionError
    ) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ProviderError)
    async def handle_provider_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ProviderError
    ) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(ConfigError)
    async def handle_config_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ConfigError
    ) -> JSONResponse:
        # Config errors may contain DSNs or key names: never echo them to clients.
        return JSONResponse({"detail": "server misconfiguration, check logs"}, status_code=500)


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    embedder: EmbeddingClient | None = None,
    store: VectorStore | None = None,
    pool: AsyncConnectionPool | None = None,
) -> FastAPI:
    """Build the FastAPI application. Injected values win over factory-built ones."""
    app_settings = settings if settings is not None else Settings()
    _configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(started_app: FastAPI) -> AsyncGenerator[None]:
        owns_pool = pool is None
        active_pool = pool if pool is not None else create_pool(app_settings)

        try:
            # Migrations BEFORE open(): the pool's configure hook runs
            # register_vector_async, which needs the `vector` type that
            # 0001_schema.sql creates. Opening first breaks every fresh database.
            if _is_real_pool(active_pool):
                await apply_migrations(active_pool)
            if owns_pool:
                await active_pool.open(wait=True, timeout=30.0)
            started_app.state.pool = active_pool

            if _is_real_pool(active_pool):
                await _ensure_embedding_config(active_pool, app_settings)
                await _sweep_interrupted_documents(active_pool)

            active_llm = llm if llm is not None else get_llm_client(app_settings)
            active_embedder = (
                embedder if embedder is not None else get_embedding_client(app_settings)
            )
            active_store = (
                store if store is not None else get_vector_store(app_settings, active_pool)
            )

            if app_settings.embedding_provider == "local":
                # First encode loads the model (10-30 s); do it before serving traffic.
                await active_embedder.embed_query("warmup")

            ingestion = IngestionService(
                pool=active_pool,
                embedder=active_embedder,
                store=active_store,
                settings=app_settings,
            )
            reranker = get_reranker(app_settings)
            if reranker is not None:
                logger.info("reranker ready", model=reranker.model)
            chat_service = ChatService(
                pool=active_pool,
                llm=active_llm,
                embedder=active_embedder,
                store=active_store,
                settings=app_settings,
                reranker=reranker,
            )

            started_app.state.llm = active_llm
            started_app.state.embedder = active_embedder
            started_app.state.store = active_store
            started_app.state.auth = ApiKeyAuth(app_settings)
            started_app.state.ingestion = ingestion
            started_app.state.chat = chat_service

            if (
                app_settings.seed_demo_data
                and _is_real_pool(active_pool)
                and await _documents_table_empty(active_pool)
            ):
                demo_dir = _resolve_demo_dir(app_settings)
                logger.info("seeding demo corpus", demo_dir=str(demo_dir))
                await ingestion.seed_demo(demo_dir)
            if _is_real_pool(active_pool):
                # Rebuild the term-frequency snapshot the hybrid query filters
                # with; a corpus ingested by a previous run left it stale.
                await ingestion.refresh_lexeme_stats()
        except BaseException:
            # A failed boot must not leak the pool it created.
            if owns_pool:
                await active_pool.close()
            raise

        logger.info(
            "application ready",
            llm_provider=app_settings.llm_provider,
            embedding_provider=app_settings.embedding_provider,
        )
        try:
            yield
        finally:
            # Drain in-flight ingestion tasks first so their audit rows land
            # before the pool goes away (hard kills rely on the boot sweep).
            await ingestion.wait_idle()
            if owns_pool:
                await active_pool.close()

    application = FastAPI(title="sovereign-rag", lifespan=lifespan)
    application.state.settings = app_settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_id_middleware(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        return response

    _register_exception_handlers(application)

    application.include_router(health_routes.router)
    application.include_router(documents_routes.router)
    application.include_router(chat_routes.router)
    application.include_router(admin_routes.router)

    return application


app = create_app()
