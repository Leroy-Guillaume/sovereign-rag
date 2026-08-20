"""Tests for the local cross-encoder reranker and its factory."""

from uuid import uuid4

import pytest

from embedding_stubs import StubCrossEncoder, install_stub_sentence_transformers
from fakes import make_settings
from sovereign_rag.reranking import get_reranker
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


def test_factory_none_returns_no_reranker() -> None:
    assert get_reranker(make_settings(reranker_provider="none")) is None


def test_factory_local_builds_the_cross_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    assert reranker.model == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    stub = StubCrossEncoder.last_instance
    assert stub is not None
    # the measured ONNX choices are pinned in the constructor, not left to defaults
    assert stub.kwargs["backend"] == "onnx"
    assert stub.kwargs["model_kwargs"]["provider"] == "CPUExecutionProvider"
    assert stub.kwargs["model_kwargs"]["file_name"] == "onnx/model_O3.onnx"
    # constructor warmup: one predict already happened
    assert len(stub.predict_calls) == 1


async def test_rerank_reorders_by_relevance_and_trims_to_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_stub_sentence_transformers(monkeypatch)
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


async def test_rerank_empty_pool_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    reranker = get_reranker(make_settings(reranker_provider="local"))
    assert reranker is not None
    stub = StubCrossEncoder.last_instance
    assert stub is not None
    warmup_calls = len(stub.predict_calls)

    assert await reranker.rerank("anything", [], k=8) == []
    assert len(stub.predict_calls) == warmup_calls  # no model call for an empty pool
