"""Test-only stub for the sentence_transformers package.

Installing the stub into sys.modules (BEFORE Settings is built) makes
EMBEDDING_PROVIDER=local usable in every environment: the Settings validator
resolves the module spec via importlib.util.find_spec, and LocalEmbedding's
lazy import picks up the stub class -- no torch, no model download, ever.
"""

import hashlib
import sys
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any

import pytest


class StubCrossEncoder:
    """Captures constructor/predict arguments; scores by shared-word count.

    Deterministic and content-sensitive: a pair sharing more words scores
    higher, so reranking tests can assert real reordering.
    """

    last_instance: "StubCrossEncoder | None" = None

    def __init__(self, model_name: str, **kwargs: Any) -> None:
        self.model_name = model_name
        self.kwargs = kwargs
        self.predict_calls: list[list[tuple[str, str]]] = []
        StubCrossEncoder.last_instance = self

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.predict_calls.append(list(pairs))
        return [
            float(len(set(query.lower().split()) & set(passage.lower().split())))
            for query, passage in pairs
        ]


class StubSentenceTransformer:
    """Captures constructor/encode arguments and returns deterministic vectors."""

    dimensions: int = 4
    last_instance: "StubSentenceTransformer | None" = None

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.encode_calls: list[tuple[list[str], dict[str, Any]]] = []
        StubSentenceTransformer.last_instance = self

    def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
        self.encode_calls.append((list(sentences), dict(kwargs)))
        return [self._vector(sentence) for sentence in sentences]

    def _vector(self, sentence: str) -> list[float]:
        digest = hashlib.sha256(sentence.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(type(self).dimensions)]


def install_stub_sentence_transformers(
    monkeypatch: pytest.MonkeyPatch, *, dimensions: int = 4
) -> type[StubSentenceTransformer]:
    """Install a fake sentence_transformers module into sys.modules for one test."""
    monkeypatch.setattr(StubSentenceTransformer, "dimensions", dimensions)
    monkeypatch.setattr(StubSentenceTransformer, "last_instance", None)
    module = ModuleType("sentence_transformers")
    # A real ModuleSpec is required: importlib.util.find_spec (used by the
    # Settings validator) raises ValueError on modules whose __spec__ is None.
    module.__spec__ = ModuleSpec("sentence_transformers", loader=None)
    module.__dict__["SentenceTransformer"] = StubSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    # The reranker imports from the sentence_transformers.cross_encoder
    # submodule; register it with the same real-ModuleSpec treatment.
    submodule = ModuleType("sentence_transformers.cross_encoder")
    submodule.__spec__ = ModuleSpec("sentence_transformers.cross_encoder", loader=None)
    submodule.__dict__["CrossEncoder"] = StubCrossEncoder
    module.__dict__["cross_encoder"] = submodule
    monkeypatch.setitem(sys.modules, "sentence_transformers.cross_encoder", submodule)
    monkeypatch.setattr(StubCrossEncoder, "last_instance", None)
    return StubSentenceTransformer
