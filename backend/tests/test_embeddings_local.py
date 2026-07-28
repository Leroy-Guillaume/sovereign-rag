"""Unit tests for the local sentence-transformers embedding adapter."""

import sys

import pytest

from embedding_stubs import StubSentenceTransformer, install_stub_sentence_transformers
from fakes import make_settings
from sovereign_rag.config import Settings
from sovereign_rag.embeddings.local import LocalEmbedding
from sovereign_rag.errors import ConfigError

E5_MODEL = "intfloat/multilingual-e5-small"


def _local_settings(model: str = E5_MODEL) -> Settings:
    return make_settings(embedding_provider="local", embedding_model=model, embedding_dimensions=4)


def _stub() -> StubSentenceTransformer:
    stub = StubSentenceTransformer.last_instance
    assert stub is not None
    return stub


async def test_e5_prefixes_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings())

    await client.embed_documents(["alpha", "beta"])
    assert _stub().encode_calls[0][0] == ["passage: alpha", "passage: beta"]

    await client.embed_query("what does the nLPD require?")
    assert _stub().encode_calls[1][0] == ["query: what does the nLPD require?"]


async def test_bge_m3_gets_no_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings(model="BAAI/bge-m3"))

    await client.embed_documents(["alpha"])
    await client.embed_query("beta")
    assert _stub().encode_calls[0][0] == ["alpha"]
    assert _stub().encode_calls[1][0] == ["beta"]


async def test_unknown_model_family_gets_no_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings(model="example/other-encoder"))

    await client.embed_documents(["alpha"])
    await client.embed_query("beta")
    assert _stub().encode_calls[0][0] == ["alpha"]
    assert _stub().encode_calls[1][0] == ["beta"]


async def test_encode_passes_normalize_embeddings_true(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings())

    await client.embed_documents(["a"])
    await client.embed_query("b")
    for _texts, kwargs in _stub().encode_calls:
        assert kwargs.get("normalize_embeddings") is True


async def test_healthcheck_embeds_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings())

    await client.healthcheck()
    assert _stub().encode_calls[0][0] == ["query: ping"]


def test_model_and_dimensions_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    client = LocalEmbedding(_local_settings())

    assert client.model == E5_MODEL
    assert client.dimensions == 4
    assert _stub().model_name == E5_MODEL  # model name forwarded to SentenceTransformer


def test_missing_dependency_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Build Settings while the stub satisfies the validator's find_spec check...
    install_stub_sentence_transformers(monkeypatch)
    settings = _local_settings()
    # ...then poison the import: a None entry in sys.modules makes
    # `from sentence_transformers import SentenceTransformer` raise ImportError.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ConfigError, match="uv sync --extra local"):
        LocalEmbedding(settings)
