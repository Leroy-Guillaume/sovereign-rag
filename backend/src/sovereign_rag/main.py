"""Application composition root.

Everything concrete is chosen here and only here: adapters come from the
provider factories, live on ``app.state`` and are read by the routes through
``request.app.state``. Tests inject fakes through ``create_app`` keyword
arguments; injected values always win over factory-built ones.

Boot sequence (lifespan): create pool -> apply migrations -> open pool ->
build adapters -> build services -> publish them on app.state. Migrations run
BEFORE the pool is opened because the pool's configure hook registers the
pgvector type adapters, which need the `vector` extension that
0001_schema.sql creates - opening first would break every boot against a
fresh database. This ordering is load-bearing, do not "tidy" it.

Interim scope: Task 14 adds the chat router and app.state.chat, Task 15 adds
the health routes, and Task 16 replaces this file with the final composition
root (structlog configuration, exception handlers, embedding-config guard,
interrupted-ingestion sweep, local-model warmup, demo seed, all three
routers).
"""

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool

from .auth import ApiKeyAuth
from .chat.service import ChatService
from .config import Settings
from .db import apply_migrations, create_pool
from .embeddings import get_embedding_client
from .embeddings.base import EmbeddingClient
from .ingestion.service import IngestionService
from .llm import get_llm_client
from .llm.base import LLMClient
from .routes.chat import router as chat_router
from .routes.documents import router as documents_router
from .routes.health import router as health_router
from .store import get_vector_store
from .store.base import VectorStore


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

    @asynccontextmanager
    async def lifespan(started_app: FastAPI) -> AsyncGenerator[None]:
        owns_pool = pool is None
        active_pool = pool if pool is not None else create_pool(app_settings)

        await apply_migrations(active_pool)
        await active_pool.open(wait=True)

        active_llm = llm if llm is not None else get_llm_client(app_settings)
        active_embedder = embedder if embedder is not None else get_embedding_client(app_settings)
        active_store = store if store is not None else get_vector_store(app_settings, active_pool)

        started_app.state.pool = active_pool
        started_app.state.llm = active_llm
        started_app.state.embedder = active_embedder
        started_app.state.store = active_store
        started_app.state.auth = ApiKeyAuth(app_settings)
        started_app.state.ingestion = IngestionService(
            pool=active_pool,
            embedder=active_embedder,
            store=active_store,
            settings=app_settings,
        )
        started_app.state.chat = ChatService(
            pool=active_pool,
            llm=active_llm,
            embedder=active_embedder,
            store=active_store,
            settings=app_settings,
        )
        try:
            yield
        finally:
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
    async def request_id_middleware(  # pyright: ignore[reportUnusedFunction] - decorator-registered
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """One correlation id per request: response header, request.state, structlog."""
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        return response

    application.include_router(documents_router)
    application.include_router(chat_router)
    application.include_router(health_router)

    return application


app = create_app()
