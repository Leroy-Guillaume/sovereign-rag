"""Azure OpenAI embedding adapter.

Uses the plain openai SDK (AsyncAzureOpenAI) -- NOT an Azure SDK. API-key auth
works with core dependencies only; keyless auth (managed identity / Entra ID)
lazily imports azure-identity from the optional [azure] extra.
"""

from collections.abc import Sequence

import httpx
from openai import AsyncAzureOpenAI, OpenAIError

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError, ProviderError

# Azure OpenAI accepts up to 2048 inputs per request, but small batches keep
# request bodies small and the error blast radius low. The ingestion service
# batches at 32 as well; batching here too makes the adapter safe for ANY
# caller, whatever input size it passes.
_BATCH_SIZE = 32
_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureEmbedding:
    """EmbeddingClient backed by an Azure OpenAI embedding deployment."""

    def __init__(self, settings: Settings) -> None:
        endpoint = settings.azure_openai_endpoint
        deployment = settings.azure_openai_embedding_deployment
        if endpoint is None or deployment is None:
            # Settings validation already enforces this for the azure_openai
            # provider; the explicit check narrows the Optional types and
            # protects direct constructor calls.
            raise ConfigError(
                "EMBEDDING_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
            )
        if settings.azure_openai_api_key is not None:
            client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=settings.azure_openai_api_key.get_secret_value(),
                api_version=settings.azure_openai_api_version,
                timeout=120,
            )
        else:
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            except ImportError as exc:
                raise ConfigError(
                    "AZURE_OPENAI_API_KEY is not set, so keyless auth is required: "
                    "uv sync --extra azure"
                ) from exc
            client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=get_bearer_token_provider(
                    DefaultAzureCredential(), _TOKEN_SCOPE
                ),
                api_version=settings.azure_openai_api_version,
                timeout=120,
            )
        self._client = client
        self._deployment = deployment
        self.model: str = settings.embedding_model
        self.dimensions: int = settings.embedding_dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = list(texts[start : start + _BATCH_SIZE])
            try:
                response = await self._client.embeddings.create(model=self._deployment, input=batch)
            except (OpenAIError, httpx.HTTPError) as exc:
                raise ProviderError(f"azure_openai embeddings request failed: {exc}") from exc
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend([float(value) for value in item.embedding] for item in ordered)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def healthcheck(self) -> None:
        """One tiny embeddings call; raises ProviderError if Azure is unreachable."""
        await self.embed_query("ping")
