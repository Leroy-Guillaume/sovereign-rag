"""Embedding client contract."""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingClient(Protocol):
    """Two methods, not one: the e5 family requires asymmetric prefixes
    ("query: " / "passage: "). That asymmetry belongs to the adapter,
    never to callers."""

    model: str  # checked against embedding_config at boot, documents.embedding_model at ingest
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def healthcheck(self) -> None: ...  # raises ProviderError -- used by /readyz
