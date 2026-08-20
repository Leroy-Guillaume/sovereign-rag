"""Local cross-encoder reranker (extra: local).

The model runs in-process over ONNX Runtime, never through an LLM server:
Ollama does not expose classification heads, and the llama.cpp /v1/rerank
route is known to return degenerate scores for these models. Two settings are
deliberate and measured on Apple Silicon / ARM:

- the execution provider is pinned to CPUExecutionProvider (the CoreML
  provider that onnxruntime would otherwise pick crashes some rerankers and
  slows others down);
- the graph-optimized fp32 export (model_O3) is used, NOT int8: dynamic int8
  is slower than fp32-O3 on ARM (the published 3x gains are AVX512-VNNI
  numbers).
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError
from sovereign_rag.store.base import SearchHit


class LocalCrossEncoderReranker:
    """Reranker backed by a sentence-transformers CrossEncoder on local CPU.

    Inference is synchronous and CPU-bound, so every predict call is pushed
    to a worker thread with asyncio.to_thread, like the embedding adapter.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
        except ImportError as exc:
            raise ConfigError(
                "RERANKER_PROVIDER=local requires the local extra: uv sync --extra local"
            ) from exc
        self.model: str = settings.reranker_model
        # Loads the weights (downloads them on first use); one tiny predict
        # warms the ONNX session so the first real query does not pay it.
        self._ce: Any = CrossEncoder(
            settings.reranker_model,
            backend="onnx",
            model_kwargs={
                "provider": "CPUExecutionProvider",
                "file_name": "onnx/model_O3.onnx",
            },
        )
        self._ce.predict([("warmup", "warmup")])

    def _scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(score) for score in self._ce.predict(pairs)]

    async def rerank(self, query: str, hits: Sequence[SearchHit], *, k: int) -> list[SearchHit]:
        if not hits:
            return []
        logits = await asyncio.to_thread(self._scores, [(query, hit.content) for hit in hits])
        # Sigmoid maps the raw logit to (0, 1) so the persisted source
        # snapshot keeps a bounded, comparable score; leg ranks are preserved
        # untouched for retrieval explainability.
        rescored = [
            replace(hit, score=1.0 / (1.0 + math.exp(-logit)))
            for hit, logit in zip(hits, logits, strict=True)
        ]
        rescored.sort(key=lambda hit: -hit.score)
        return rescored[:k]
