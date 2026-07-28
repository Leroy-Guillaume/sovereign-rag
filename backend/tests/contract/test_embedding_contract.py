"""Contract suite: every EmbeddingClient implementation obeys the same rules.

Parametrized over FakeEmbedding (tests/fakes.py), LocalEmbedding backed by a
stubbed sentence_transformers module, and AzureEmbedding backed by respx.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from embedding_stubs import install_stub_sentence_transformers
from fakes import FakeEmbedding, make_settings
from sovereign_rag.embeddings.azure import AzureEmbedding
from sovereign_rag.embeddings.base import EmbeddingClient
from sovereign_rag.embeddings.local import LocalEmbedding

DIMENSIONS = 8
AZURE_ENDPOINT = "https://unit.openai.azure.com"
AZURE_EMBED_URL = f"{AZURE_ENDPOINT}/openai/deployments/embed-dep/embeddings"


def _azure_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {
            "object": "embedding",
            "index": index,
            "embedding": [float(index + 1)] * DIMENSIONS,
        }
        for index in range(len(body["input"]))
    ]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": data,
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )


@pytest.fixture(params=["fake", "local", "azure"])
def client(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[EmbeddingClient]:
    param: str = request.param
    if param == "fake":
        yield FakeEmbedding(dimensions=DIMENSIONS)
    elif param == "local":
        install_stub_sentence_transformers(monkeypatch, dimensions=DIMENSIONS)
        settings = make_settings(
            embedding_provider="local",
            embedding_model="intfloat/multilingual-e5-small",
            embedding_dimensions=DIMENSIONS,
        )
        yield LocalEmbedding(settings)
    else:
        # Bare `respx.mock` context: no assert-all-called, so tests that make
        # zero HTTP calls (empty input) pass for the azure param too.
        with respx.mock:
            respx.post(AZURE_EMBED_URL).mock(side_effect=_azure_response)
            settings = make_settings(
                embedding_provider="azure_openai",
                embedding_model="text-embedding-3-small",
                embedding_dimensions=DIMENSIONS,
                azure_openai_endpoint=AZURE_ENDPOINT,
                azure_openai_api_key="unit-test-key",
                azure_openai_embedding_deployment="embed-dep",
            )
            yield AzureEmbedding(settings)


async def test_embed_documents_one_vector_per_text(client: EmbeddingClient) -> None:
    texts = ["alpha", "beta", "gamma"]
    vectors = await client.embed_documents(texts)
    assert len(vectors) == len(texts)
    assert all(len(vector) == client.dimensions for vector in vectors)


async def test_embed_query_returns_dimensions_length_vector(client: EmbeddingClient) -> None:
    vector = await client.embed_query("what is the data retention period?")
    assert len(vector) == client.dimensions
    assert all(isinstance(value, float) for value in vector)


async def test_embed_documents_empty_input_returns_empty_list(client: EmbeddingClient) -> None:
    assert await client.embed_documents([]) == []


async def test_model_attribute_is_a_nonempty_string(client: EmbeddingClient) -> None:
    assert isinstance(client.model, str)
    assert client.model
