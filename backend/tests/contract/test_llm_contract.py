"""Contract suite for every LLMClient implementation.

Task 7 introduced this suite with FakeLLM as its only case. This version adds
the three real adapters, each exercised against a respx mock that pins the
exact provider wire format:

- Ollama: native /api/chat, JSON-lines streaming, final line carrying
  prompt_eval_count / eval_count, request body carrying think/keep_alive;
- OpenAI-compatible: SSE chat.completions chunks, usage in the final chunk
  (stream_options.include_usage);
- Azure OpenAI: the same SSE format on the Azure deployment URL shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
import respx

from fakes import FakeLLM, make_settings
from sovereign_rag.config import Settings
from sovereign_rag.errors import ProviderError
from sovereign_rag.llm import get_llm_client
from sovereign_rag.llm.base import ChatMessage, LLMClient, collect

MESSAGES = (
    ChatMessage(role="system", content="You are a test assistant."),
    ChatMessage(role="user", content="Hi"),
)

OLLAMA_BASE = "http://ollama.test:11434"
COMPAT_BASE = "http://vllm.test/v1"
AZURE_ENDPOINT = "https://example-aoai.openai.azure.com"
AZURE_DEPLOYMENT = "gpt-4o-mini"
_AZURE_CHAT_URL = f"{AZURE_ENDPOINT}/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions"
AZURE_CHAT_RE = re.escape(_AZURE_CHAT_URL) + r"\?.*"
AZURE_MODELS_RE = re.escape(f"{AZURE_ENDPOINT}/openai/models") + r"\?.*"

# The openai SDK retries 5xx responses by default; it honours this response
# header and skips its retries, keeping the error-mapping tests instant.
_NO_RETRY = {"x-should-retry": "false"}


def _ollama_settings() -> Settings:
    return make_settings(llm_provider="ollama", ollama_base_url=OLLAMA_BASE)


def _compat_settings() -> Settings:
    return make_settings(
        llm_provider="openai_compatible",
        openai_compat_base_url=COMPAT_BASE,
        openai_compat_api_key="sk-test",
        openai_compat_model="test-model",
    )


def _azure_settings() -> Settings:
    return make_settings(
        llm_provider="azure_openai",
        azure_openai_endpoint=AZURE_ENDPOINT,
        azure_openai_api_key="azure-key",
        azure_openai_chat_deployment=AZURE_DEPLOYMENT,
    )


def _ollama_stream_body() -> bytes:
    """Native Ollama /api/chat streaming response: one JSON object per line."""
    lines: list[dict[str, object]] = [
        {"model": "qwen3:4b", "message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"model": "qwen3:4b", "message": {"role": "assistant", "content": " world"}, "done": False},
        {
            "model": "qwen3:4b",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        },
    ]
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


def _openai_sse_body(model: str) -> bytes:
    """OpenAI chat.completions SSE stream with usage in the final chunk."""
    base: dict[str, object] = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
    }
    payloads: list[dict[str, object]] = [
        {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": None,
                }
            ],
        },
        {
            **base,
            "choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}],
        },
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {
            **base,
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    ]
    body = b"".join(b"data: " + json.dumps(payload).encode() + b"\n\n" for payload in payloads)
    return body + b"data: [DONE]\n\n"


@dataclass(frozen=True)
class Case:
    """One LLMClient implementation plus the wire mocks it needs."""

    name: str
    ok: Callable[[respx.MockRouter], LLMClient]
    stream_error: Callable[[respx.MockRouter], LLMClient]
    health_ok: Callable[[respx.MockRouter], LLMClient]
    health_error: Callable[[respx.MockRouter], LLMClient] | None


def _fake_ok(_router: respx.MockRouter) -> LLMClient:
    return FakeLLM(chunks=["Hello", " world"])


def _fake_stream_error(_router: respx.MockRouter) -> LLMClient:
    return FakeLLM(chunks=["Hello", " world"], fail_after=1)


def _fake_health_ok(_router: respx.MockRouter) -> LLMClient:
    return FakeLLM()


def _ollama_ok(router: respx.MockRouter) -> LLMClient:
    router.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            content=_ollama_stream_body(),
            headers={"content-type": "application/x-ndjson"},
        )
    )
    return get_llm_client(_ollama_settings())


def _ollama_stream_error(router: respx.MockRouter) -> LLMClient:
    router.post(f"{OLLAMA_BASE}/api/chat").mock(return_value=httpx.Response(503))
    return get_llm_client(_ollama_settings())


def _ollama_health_ok(router: respx.MockRouter) -> LLMClient:
    router.get(f"{OLLAMA_BASE}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    return get_llm_client(_ollama_settings())


def _ollama_health_error(router: respx.MockRouter) -> LLMClient:
    router.get(f"{OLLAMA_BASE}/api/tags").mock(return_value=httpx.Response(503))
    return get_llm_client(_ollama_settings())


def _compat_ok(router: respx.MockRouter) -> LLMClient:
    router.post(f"{COMPAT_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=_openai_sse_body("test-model"),
            headers={"content-type": "text/event-stream"},
        )
    )
    return get_llm_client(_compat_settings())


def _compat_stream_error(router: respx.MockRouter) -> LLMClient:
    router.post(f"{COMPAT_BASE}/chat/completions").mock(
        return_value=httpx.Response(503, headers=_NO_RETRY, json={"error": "unavailable"})
    )
    return get_llm_client(_compat_settings())


def _compat_health_ok(router: respx.MockRouter) -> LLMClient:
    router.get(f"{COMPAT_BASE}/models").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )
    return get_llm_client(_compat_settings())


def _compat_health_error(router: respx.MockRouter) -> LLMClient:
    router.get(f"{COMPAT_BASE}/models").mock(
        return_value=httpx.Response(503, headers=_NO_RETRY, json={"error": "unavailable"})
    )
    return get_llm_client(_compat_settings())


def _azure_ok(router: respx.MockRouter) -> LLMClient:
    router.post(url__regex=AZURE_CHAT_RE).mock(
        return_value=httpx.Response(
            200,
            content=_openai_sse_body(AZURE_DEPLOYMENT),
            headers={"content-type": "text/event-stream"},
        )
    )
    return get_llm_client(_azure_settings())


def _azure_stream_error(router: respx.MockRouter) -> LLMClient:
    router.post(url__regex=AZURE_CHAT_RE).mock(
        return_value=httpx.Response(503, headers=_NO_RETRY, json={"error": "unavailable"})
    )
    return get_llm_client(_azure_settings())


def _azure_health_ok(router: respx.MockRouter) -> LLMClient:
    router.get(url__regex=AZURE_MODELS_RE).mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )
    return get_llm_client(_azure_settings())


def _azure_health_error(router: respx.MockRouter) -> LLMClient:
    router.get(url__regex=AZURE_MODELS_RE).mock(
        return_value=httpx.Response(503, headers=_NO_RETRY, json={"error": "unavailable"})
    )
    return get_llm_client(_azure_settings())


CASES: list[Case] = [
    Case(
        name="fake",
        ok=_fake_ok,
        stream_error=_fake_stream_error,
        health_ok=_fake_health_ok,
        health_error=None,  # FakeLLM.healthcheck never fails by design
    ),
    Case(
        name="ollama",
        ok=_ollama_ok,
        stream_error=_ollama_stream_error,
        health_ok=_ollama_health_ok,
        health_error=_ollama_health_error,
    ),
    Case(
        name="openai_compat",
        ok=_compat_ok,
        stream_error=_compat_stream_error,
        health_ok=_compat_health_ok,
        health_error=_compat_health_error,
    ),
    Case(
        name="azure",
        ok=_azure_ok,
        stream_error=_azure_stream_error,
        health_ok=_azure_health_ok,
        health_error=_azure_health_error,
    ),
]
CASE_IDS = [case.name for case in CASES]
ADAPTER_CASES = [case for case in CASES if case.health_error is not None]
ADAPTER_CASE_IDS = [case.name for case in ADAPTER_CASES]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_stream_chat_yields_text_then_final_usage(case: Case) -> None:
    with respx.mock(assert_all_called=False) as router:
        client = case.ok(router)
        chunks = [chunk async for chunk in client.stream_chat(MESSAGES)]

    assert "".join(chunk.delta for chunk in chunks) == "Hello world"
    assert chunks[-1].prompt_tokens == 10
    assert chunks[-1].completion_tokens == 5


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_collect_returns_text_and_usage(case: Case) -> None:
    with respx.mock(assert_all_called=False) as router:
        client = case.ok(router)
        text, prompt_tokens, completion_tokens = await collect(client.stream_chat(MESSAGES))

    assert text == "Hello world"
    assert prompt_tokens == 10
    assert completion_tokens == 5


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_stream_failure_raises_provider_error(case: Case) -> None:
    with respx.mock(assert_all_called=False) as router:
        client = case.stream_error(router)
        with pytest.raises(ProviderError):
            async for _ in client.stream_chat(MESSAGES):
                pass


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_healthcheck_ok(case: Case) -> None:
    with respx.mock(assert_all_called=False) as router:
        client = case.health_ok(router)
        await client.healthcheck()


@pytest.mark.parametrize("case", ADAPTER_CASES, ids=ADAPTER_CASE_IDS)
async def test_healthcheck_failure_raises_provider_error(case: Case) -> None:
    mock_health_error = case.health_error
    assert mock_health_error is not None  # ADAPTER_CASES filters the fake out
    with respx.mock(assert_all_called=False) as router:
        client = mock_health_error(router)
        with pytest.raises(ProviderError):
            await client.healthcheck()


async def test_ollama_wire_format_pins_native_api_and_disables_think() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{OLLAMA_BASE}/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=_ollama_stream_body(),
                headers={"content-type": "application/x-ndjson"},
            )
        )
        client = get_llm_client(_ollama_settings())
        text, _, _ = await collect(client.stream_chat(MESSAGES, temperature=0.2, max_tokens=64))

    assert text == "Hello world"
    assert client.model == "qwen3:4b"
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "qwen3:4b"
    assert body["stream"] is True
    assert body["think"] is False  # keeps qwen3 <think> blocks out of the stream
    assert body["keep_alive"] == "10m"
    assert body["options"] == {"temperature": 0.2, "num_predict": 64}
    assert body["messages"] == [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "Hi"},
    ]


async def test_ollama_error_message_mentions_base_url() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{OLLAMA_BASE}/api/chat").mock(return_value=httpx.Response(503))
        client = get_llm_client(_ollama_settings())
        with pytest.raises(ProviderError) as exc_info:
            async for _ in client.stream_chat(MESSAGES):
                pass

    message = str(exc_info.value)
    assert "Ollama" in message
    assert OLLAMA_BASE in message


async def test_openai_compat_wire_format_requests_usage() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{COMPAT_BASE}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=_openai_sse_body("test-model"),
                headers={"content-type": "text/event-stream"},
            )
        )
        client = get_llm_client(_compat_settings())
        text, prompt_tokens, completion_tokens = await collect(client.stream_chat(MESSAGES))

    assert (text, prompt_tokens, completion_tokens) == ("Hello world", 10, 5)
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 1024


async def test_azure_wire_format_targets_deployment_url() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url__regex=AZURE_CHAT_RE).mock(
            return_value=httpx.Response(
                200,
                content=_openai_sse_body(AZURE_DEPLOYMENT),
                headers={"content-type": "text/event-stream"},
            )
        )
        client = get_llm_client(_azure_settings())
        text, prompt_tokens, completion_tokens = await collect(client.stream_chat(MESSAGES))

    assert (text, prompt_tokens, completion_tokens) == ("Hello world", 10, 5)
    assert client.model == AZURE_DEPLOYMENT  # the deployment name is the adapter's model
    request = route.calls.last.request
    assert request.url.path == f"/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions"
    assert request.url.params["api-version"] == "2024-10-21"
    assert request.headers["api-key"] == "azure-key"
    body = json.loads(request.content)
    assert body["stream_options"] == {"include_usage": True}
