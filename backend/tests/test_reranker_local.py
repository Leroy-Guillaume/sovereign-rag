"""Tests for the local cross-encoder reranker and its factory.

The adapter drives an ONNX session directly; the stubs replace the session,
the tokenizer and the snapshot resolution with pair-aware fakes that score by
shared-word count, so reordering tests assert real rank changes without any
model download.
"""

from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import pytest

from embedding_stubs import install_stub_sentence_transformers
from fakes import make_settings
from sovereign_rag.reranking import get_reranker
from sovereign_rag.reranking.local import (
    MODEL_FILE,
    SNAPSHOT_PATTERNS,
    TORCH_SNAPSHOT_PATTERNS,
)
from sovereign_rag.store.base import SearchHit


def _hit(content: str, *, score: float = 0.01, vec: int | None = 1) -> SearchHit:
    return SearchHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="doc.md",
        section=None,
        page=None,
        content=content,
        score=score,
        vec_rank=vec,
        fts_rank=None,
    )


class _StubSession:
    """ONNX session double: logit = shared-word count of each (query, passage).

    The pairs travel through a shared mutable list the stub tokenizer fills,
    mirroring how the real tokenizer output feeds the real session.
    """

    created: ClassVar[list["_StubSession"]] = []

    def __init__(self, path: str, providers: list[str], pairs_box: list[tuple[str, str]]) -> None:
        self.path = path
        self.providers = providers
        self._pairs_box = pairs_box
        self.run_calls = 0
        _StubSession.created.append(self)

    def get_inputs(self) -> list[Any]:
        class _Input:
            name = "input_ids"

        return [_Input()]

    def run(self, _outputs: None, inputs: dict[str, Any]) -> list[list[list[float]]]:
        del inputs
        self.run_calls += 1
        return [
            [
                [float(len(set(query.lower().split()) & set(passage.lower().split())))]
                for query, passage in self._pairs_box
            ]
        ]


def _install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stub every loader the adapter touches."""
    install_stub_sentence_transformers(monkeypatch)  # find_spec guard in Settings
    import huggingface_hub
    import onnxruntime  # pyright: ignore[reportMissingTypeStubs]
    import transformers

    snapshot = tmp_path / "snapshot"
    (snapshot / "onnx").mkdir(parents=True, exist_ok=True)
    (snapshot / "onnx" / "model_O3.onnx").write_bytes(b"stub")
    pairs_box: list[tuple[str, str]] = []

    def fake_snapshot(model: str, allow_patterns: list[str]) -> str:
        assert allow_patterns in (SNAPSHOT_PATTERNS, TORCH_SNAPSHOT_PATTERNS)
        return str(snapshot)

    def fake_tokenize(queries: list[str], passages: list[str], **kwargs: Any) -> dict[str, Any]:
        pairs_box[:] = list(zip(queries, passages, strict=True))
        return {"input_ids": [[0]] * len(queries), "token_type_ids": [[0]] * len(queries)}

    def fake_from_pretrained(source: str) -> Any:
        del source
        return fake_tokenize

    def fake_session(path: str, providers: list[str]) -> _StubSession:
        return _StubSession(path, providers, pairs_box)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    monkeypatch.setattr(
        transformers.AutoTokenizer, "from_pretrained", staticmethod(fake_from_pretrained)
    )
    monkeypatch.setattr(onnxruntime, "InferenceSession", fake_session)
    _StubSession.created.clear()


def test_factory_none_returns_no_reranker() -> None:
    assert get_reranker(make_settings(reranker_provider="none")) is None


def test_factory_local_builds_the_onnx_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch, tmp_path)
    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    assert reranker.model == "BAAI/bge-reranker-v2-m3"
    [session] = _StubSession.created
    # the measured ONNX choices are pinned in the constructor, not left to defaults
    assert session.providers == ["CPUExecutionProvider"]
    assert session.path.endswith(MODEL_FILE)
    # constructor warmup: one inference already happened
    assert session.run_calls == 1


async def test_rerank_reorders_by_relevance_and_trims_to_k(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch, tmp_path)
    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    hits = [
        _hit("warehouse logistics quarterly review"),
        _hit("encryption keys protect encrypted backups"),
        _hit("encryption policy"),
    ]

    top = await reranker.rerank("encryption keys", hits, k=2)

    assert len(top) == 2
    assert top[0].content == "encryption keys protect encrypted backups"
    assert top[1].content == "encryption policy"
    # scores are sigmoid-bounded and ordered; leg ranks survive untouched
    assert 0.0 < top[1].score < top[0].score < 1.0
    assert top[0].vec_rank == 1 and top[0].fts_rank is None


async def test_rerank_empty_pool_short_circuits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch, tmp_path)
    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    [session] = _StubSession.created
    warmup_calls = session.run_calls

    assert await reranker.rerank("anything", [], k=8) == []
    assert session.run_calls == warmup_calls  # no model call for an empty pool


async def test_missing_onnx_export_falls_back_to_torch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A model without a published ONNX export (bge-reranker-v2-m3) must load
    through the transformers path, on the same tokenizer and scoring code."""
    install_stub_sentence_transformers(monkeypatch)
    import huggingface_hub
    import onnxruntime  # pyright: ignore[reportMissingTypeStubs]
    import transformers

    snapshot = tmp_path / "torch-only"
    snapshot.mkdir()
    requested: list[list[str]] = []

    def fake_snapshot(model: str, allow_patterns: list[str]) -> str:
        requested.append(list(allow_patterns))
        return str(snapshot)  # never contains onnx/model_O3.onnx

    class _TorchLogits:
        def __init__(self, n: int) -> None:
            self.logits = [[float(i)] for i in range(n)]

    class _StubTorchModel:
        loaded: ClassVar[list[str]] = []

        @staticmethod
        def from_pretrained(source: str) -> "_StubTorchModel":
            _StubTorchModel.loaded.append(source)
            return _StubTorchModel()

        def eval(self) -> None:
            return None

        def __call__(self, **encoded: Any) -> _TorchLogits:
            return _TorchLogits(len(encoded["input_ids"]))

    def fake_tokenize(queries: list[str], passages: list[str], **kwargs: Any) -> dict[str, Any]:
        assert kwargs["return_tensors"] == "pt", "the torch path must tokenize to tensors"
        return {"input_ids": [[0]] * len(queries), "attention_mask": [[1]] * len(queries)}

    def fail_session(path: str, providers: list[str]) -> None:
        raise AssertionError("the ONNX session must not be built without an export")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)

    def fake_from_pretrained(source: str) -> Any:
        del source
        return fake_tokenize

    monkeypatch.setattr(
        transformers.AutoTokenizer, "from_pretrained", staticmethod(fake_from_pretrained)
    )
    monkeypatch.setattr(
        transformers, "AutoModelForSequenceClassification", _StubTorchModel, raising=False
    )
    monkeypatch.setattr(onnxruntime, "InferenceSession", fail_session)

    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    # both snapshot passes happened: onnx first, then the torch weights
    assert requested == [SNAPSHOT_PATTERNS, TORCH_SNAPSHOT_PATTERNS]
    assert _StubTorchModel.loaded == [str(snapshot)]

    hits = [_hit("a"), _hit("b"), _hit("c")]
    top = await reranker.rerank("q", hits, k=2)
    # stub logits are the pair index: the LAST pair scores highest
    assert [h.content for h in top] == ["c", "b"]
