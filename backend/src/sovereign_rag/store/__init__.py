"""Vector store factory: the only place that picks a concrete implementation."""

from typing import assert_never

from psycopg_pool import AsyncConnectionPool

from sovereign_rag.config import Settings

from .base import VectorStore


def get_vector_store(settings: Settings, pool: AsyncConnectionPool) -> VectorStore:
    """Build the configured VectorStore.

    Lazy import inside the match branch, same pattern as the LLM/embedding
    factories; assert_never makes pyright enforce exhaustiveness when a new
    backend is added to the Literal.
    """
    match settings.vector_store:
        case "pgvector":
            from .pgvector import PgVectorStore

            return PgVectorStore(
                pool,
                candidates=settings.retrieval_candidates,
                rrf_k=settings.rrf_k,
                weight_fts=settings.rrf_weight_fts,
                per_document_cap=settings.fusion_per_document_cap,
                ef_search=settings.hnsw_ef_search,
            )
        case _:
            assert_never(settings.vector_store)
