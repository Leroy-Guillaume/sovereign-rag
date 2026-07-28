"""EmbeddingClient Protocol -- the contract every embedding adapter satisfies."""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingClient(Protocol):
    """Contract: embed_documents returns exactly one vector per input text, in
    input order, each of length `dimensions`. Asymmetric model prefixes (e.g.
    e5's "query: "/"passage: ") are the adapter's concern -- callers always
    pass raw text. Network/provider failures raise ProviderError; httpx/openai
    exceptions never leak. healthcheck raises on failure (used by /readyz)."""

    model: str  # checked against embedding_config at boot, documents.embedding_model at ingest
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def healthcheck(self) -> None: ...
