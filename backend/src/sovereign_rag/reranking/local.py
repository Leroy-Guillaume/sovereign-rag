"""Local cross-encoder reranker (extra: local).

The model runs in-process over ONNX Runtime, never through an LLM server:
Ollama does not expose classification heads, and the llama.cpp /v1/rerank
route is known to return degenerate scores for these models. The ONNX session
is driven directly rather than through optimum: every optimum flavour pins
transformers below the 5.x line, which carries two fixed HIGH CVEs
(CVE-2026-4372, CVE-2026-5241), and the session-side code is a dozen lines.

Two settings are deliberate and measured on Apple Silicon / ARM:

- the execution provider is pinned to CPUExecutionProvider (the CoreML
  provider that onnxruntime would otherwise pick crashes some rerankers and
  slows others down);
- the graph-optimized fp32 export (model_O3) is used, NOT int8: dynamic int8
  is slower than fp32-O3 on ARM (the published 3x gains are AVX512-VNNI
  numbers).

Verified against the torch CrossEncoder reference: logits match to three
decimals on identical pairs.
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError
from sovereign_rag.store.base import SearchHit

# The exact files the reranker needs; everything else in the model repository
# stays out of the image. Mirrored by the bake step in backend/Dockerfile --
# keep the two in sync. Models that publish a graph-optimized ONNX export
# (the default mmarco does) run over ONNX Runtime; models that ship only
# torch weights (bge-reranker-v2-m3) fall back to a plain transformers
# forward pass on the same tokenizer/scoring path, so switching models stays
# one setting, not one adapter.
# model_O3.onnx plus its optional external-data sibling (graphs over
# protobuf's 2 GB cap store their weights in a companion file).
MODEL_FILE = "onnx/model_O3.onnx"
_COMMON_PATTERNS = [
    "config.json",
    "tokenizer*",
    "special_tokens_map.json",
    "sentencepiece*",
]
SNAPSHOT_PATTERNS = [*_COMMON_PATTERNS, MODEL_FILE + "*"]
TORCH_SNAPSHOT_PATTERNS = [*_COMMON_PATTERNS, "*.safetensors"]


class LocalCrossEncoderReranker:
    """Reranker running a cross-encoder ONNX session on the local CPU.

    Inference is synchronous and CPU-bound, so every scoring call is pushed
    to a worker thread with asyncio.to_thread, like the embedding adapter.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            # onnxruntime ships no stubs and the two loaders are partially
            # untyped under strict mode; the adapter pins its own narrow
            # types on the results instead.
            import onnxruntime  # pyright: ignore[reportMissingTypeStubs]
            from huggingface_hub import (
                snapshot_download,  # pyright: ignore[reportUnknownVariableType]
            )
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise ConfigError(
                "RERANKER_PROVIDER=local requires the local extra: uv sync --extra local"
            ) from exc
        self.model: str = settings.reranker_model
        source = settings.reranker_model
        if not Path(source).is_dir():
            # Resolves the hub id to a local snapshot: served straight from
            # the cache under HF_HUB_OFFLINE=1 (the baked image), downloaded
            # on first use otherwise.
            source = snapshot_download(source, allow_patterns=SNAPSHOT_PATTERNS)
        if not (Path(source) / MODEL_FILE).is_file() and not Path(settings.reranker_model).is_dir():
            # No published ONNX export: fetch the torch weights instead and
            # take the transformers path below.
            source = snapshot_download(
                settings.reranker_model, allow_patterns=TORCH_SNAPSHOT_PATTERNS
            )
        self._tokenizer: Any = AutoTokenizer.from_pretrained(  # pyright: ignore[reportUnknownMemberType]
            source
        )
        self._session: Any = None
        self._model: Any = None
        if (Path(source) / MODEL_FILE).is_file():
            self._session = onnxruntime.InferenceSession(
                str(Path(source) / MODEL_FILE), providers=["CPUExecutionProvider"]
            )
            self._input_names: set[str] = {i.name for i in self._session.get_inputs()}
        else:
            from transformers import AutoModelForSequenceClassification

            self._model = AutoModelForSequenceClassification.from_pretrained(  # pyright: ignore[reportUnknownMemberType]
                source
            )
            self._model.eval()  # pyright: ignore[reportUnknownMemberType]
        # One tiny inference warms the execution path so the first real query
        # does not pay the initialization cost.
        self._scores([("warmup", "warmup")])

    def _scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        tensors = "np" if self._session is not None else "pt"
        encoded = self._tokenizer(
            [query for query, _ in pairs],
            [passage for _, passage in pairs],
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors=tensors,
        )
        if self._session is not None:
            inputs = {
                name: array for name, array in dict(encoded).items() if name in self._input_names
            }
            logits = self._session.run(None, inputs)[0]
            return [float(row[0]) for row in logits]
        import torch

        with torch.no_grad():
            logits = self._model(**encoded).logits
        return [float(row[0]) for row in logits]

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
