"""Unit tests for the Azure OpenAI embedding adapter (HTTP mocked with respx)."""

import json
import sys
from typing import Any, cast

import httpx
import pytest
import respx
from respx.models import Call

from fakes import make_settings
from sovereign_rag.config import Settings
from sovereign_rag.embeddings.azure import AzureEmbedding
from sovereign_rag.errors import ConfigError, ProviderError

ENDPOINT = "https://unit.openai.azure.com"
DEPLOYMENT = "embed-dep"
EMBED_URL = f"{ENDPOINT}/openai/deployments/{DEPLOYMENT}/embeddings"


def _azure_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "embedding_provider": "azure_openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 3,
        "azure_openai_endpoint": ENDPOINT,
        "azure_openai_api_key": "unit-test-key",
        "azure_openai_embedding_deployment": DEPLOYMENT,
    }
    values.update(overrides)
    return make_settings(**values)


def _embedding_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"object": "embedding", "index": index, "embedding": [0.1, 0.2, 0.3]}
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


@respx.mock
async def test_embed_documents_batches_inputs_by_32() -> None:
    route = respx.post(EMBED_URL).mock(side_effect=_embedding_response)
    client = AzureEmbedding(_azure_settings())

    vectors = await client.embed_documents([f"text {i}" for i in range(70)])

    assert len(vectors) == 70
    assert all(vector == [0.1, 0.2, 0.3] for vector in vectors)
    # respx's CallList extends the bare `list` type, so its elements are
    # untyped under strict pyright; one cast restores the element type.
    calls = cast("list[Call]", route.calls)
    sizes = [len(json.loads(call.request.content)["input"]) for call in calls]
    assert sizes == [32, 32, 6]
    body = json.loads(calls[0].request.content)
    assert body["model"] == DEPLOYMENT  # the SDK routes by deployment name


@respx.mock
async def test_embed_query_returns_single_vector() -> None:
    respx.post(EMBED_URL).mock(side_effect=_embedding_response)
    client = AzureEmbedding(_azure_settings())

    vector = await client.embed_query("what is LIPAD?")

    assert vector == [0.1, 0.2, 0.3]
    assert client.dimensions == 3
    assert client.model == "text-embedding-3-small"


@respx.mock
async def test_api_failure_raises_provider_error() -> None:
    # 400 is not retried by the openai SDK, so the test stays fast.
    respx.post(EMBED_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"message": "bad request", "type": "invalid_request_error"}},
        )
    )
    client = AzureEmbedding(_azure_settings())

    with pytest.raises(ProviderError, match="azure_openai embeddings request failed"):
        await client.embed_documents(["text"])


@respx.mock
async def test_healthcheck_calls_embedding_deployment() -> None:
    route = respx.post(EMBED_URL).mock(side_effect=_embedding_response)
    client = AzureEmbedding(_azure_settings())

    await client.healthcheck()

    assert route.called


def test_keyless_without_azure_extra_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # None entries in sys.modules make `from azure.identity import ...` raise
    # ImportError even when azure-identity happens to be installed locally.
    monkeypatch.setitem(sys.modules, "azure", None)
    monkeypatch.setitem(sys.modules, "azure.identity", None)
    settings = _azure_settings(azure_openai_api_key=None)

    with pytest.raises(ConfigError, match="uv sync --extra azure"):
        AzureEmbedding(settings)
