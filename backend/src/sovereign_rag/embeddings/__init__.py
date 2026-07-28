"""Embedding adapter factory.

Concrete adapters are imported lazily inside the match so the default profile
never imports SDKs it does not need (torch stays out of Azure-profile images,
azure-identity stays out of local-profile images).
"""

from typing import assert_never

from sovereign_rag.config import Settings
from sovereign_rag.embeddings.base import EmbeddingClient

__all__ = ["EmbeddingClient", "get_embedding_client"]


def get_embedding_client(settings: Settings) -> EmbeddingClient:
    match settings.embedding_provider:
        case "local":
            from sovereign_rag.embeddings.local import LocalEmbedding

            return LocalEmbedding(settings)
        case "azure_openai":
            from sovereign_rag.embeddings.azure import AzureEmbedding

            return AzureEmbedding(settings)
        case _:
            assert_never(settings.embedding_provider)
