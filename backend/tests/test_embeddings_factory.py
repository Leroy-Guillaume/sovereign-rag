"""Factory tests: provider literal -> concrete adapter, imported lazily."""

import pytest

from embedding_stubs import install_stub_sentence_transformers
from fakes import make_settings
from sovereign_rag.embeddings import get_embedding_client
from sovereign_rag.embeddings.azure import AzureEmbedding
from sovereign_rag.embeddings.local import LocalEmbedding


def test_factory_returns_local_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    install_stub_sentence_transformers(monkeypatch)
    settings = make_settings(
        embedding_provider="local",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_dimensions=4,
    )

    client = get_embedding_client(settings)

    assert isinstance(client, LocalEmbedding)
    assert client.model == "intfloat/multilingual-e5-small"


def test_factory_returns_azure_embedding() -> None:
    settings = make_settings(
        embedding_provider="azure_openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        azure_openai_endpoint="https://unit.openai.azure.com",
        azure_openai_api_key="unit-test-key",
        azure_openai_embedding_deployment="embed-dep",
    )

    client = get_embedding_client(settings)

    assert isinstance(client, AzureEmbedding)
    assert client.dimensions == 3
