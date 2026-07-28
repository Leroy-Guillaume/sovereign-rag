"""Local embedding adapter backed by sentence-transformers (extra: local)."""

import asyncio
from collections.abc import Sequence
from typing import Any

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError

# Asymmetric prefixes by model family, matched as substrings of the model name.
# The e5 family was trained with "query: "/"passage: " prefixes -- omitting
# them measurably degrades retrieval quality. bge-m3 was trained without
# prefixes. The asymmetry belongs to the adapter: callers never see prefixes.
PREFIXES: dict[str, tuple[str, str]] = {
    "e5": ("query: ", "passage: "),
    "bge-m3": ("", ""),
}
_DEFAULT_PREFIXES: tuple[str, str] = ("", "")


def _prefixes_for(model_name: str) -> tuple[str, str]:
    """Return (query_prefix, passage_prefix) for a model name."""
    for family, prefixes in PREFIXES.items():
        if family in model_name:
            return prefixes
    return _DEFAULT_PREFIXES


class LocalEmbedding:
    """EmbeddingClient running a sentence-transformers model on the local CPU.

    Inference is synchronous and CPU-bound, so every encode call is pushed to
    a worker thread with asyncio.to_thread to keep the event loop responsive.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ConfigError(
                "EMBEDDING_PROVIDER=local requires the local extra: uv sync --extra local"
            ) from exc
        self.model: str = settings.embedding_model
        self.dimensions: int = settings.embedding_dimensions
        self._query_prefix, self._passage_prefix = _prefixes_for(settings.embedding_model)
        # Loads the model weights (downloads them on first use).
        self._st: Any = SentenceTransformer(settings.embedding_model)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._st.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefixed = [f"{self._passage_prefix}{text}" for text in texts]
        return await asyncio.to_thread(self._encode, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._encode, [f"{self._query_prefix}{text}"])
        return vectors[0]

    async def healthcheck(self) -> None:
        """Embed a trivial query; raises if the model cannot produce vectors."""
        await self.embed_query("ping")
