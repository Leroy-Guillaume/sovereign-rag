"""Contract suite for every LLMClient implementation.

Parametrized over CLIENT_FACTORIES: each entry is a zero-argument callable
returning an async context manager that yields a ready-to-use client. Task 7
registers FakeLLM only; the adapter tasks append factories for OllamaLLM and
OpenAICompatLLM (backed by respx-mocked transports) and AzureOpenAILLM, and every
test below runs against each of them unchanged.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest

from fakes import FakeLLM
from sovereign_rag.llm.base import ChatMessage, LLMClient

ClientFactory = Callable[[], AbstractAsyncContextManager[LLMClient]]


def _fake_llm_conforms_to_protocol() -> LLMClient:  # pyright: ignore[reportUnusedFunction]
    # Static assertion: pyright (strict) verifies here that FakeLLM structurally
    # satisfies the LLMClient Protocol. Never called at runtime.
    return FakeLLM()


@asynccontextmanager
async def _fake_llm() -> AsyncGenerator[LLMClient]:
    yield FakeLLM()


CLIENT_FACTORIES: list[ClientFactory] = [
    _fake_llm,
    # Adapter tasks append here: _ollama_llm, _openai_compat_llm, _azure_llm.
]


@pytest.fixture(params=CLIENT_FACTORIES, ids=lambda factory: factory.__name__.strip("_"))
async def client(request: pytest.FixtureRequest) -> AsyncIterator[LLMClient]:
    factory: ClientFactory = request.param
    async with factory() as built:
        yield built


def _messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are a test assistant."),
        ChatMessage(role="user", content="Say hello."),
    ]


async def test_model_is_a_nonempty_string(client: LLMClient) -> None:
    assert type(client.model) is str
    assert client.model


async def test_stream_chat_yields_at_least_one_chunk(client: LLMClient) -> None:
    chunks = [chunk async for chunk in client.stream_chat(_messages())]
    assert len(chunks) >= 1


async def test_usage_sits_on_the_final_chunk_only(client: LLMClient) -> None:
    chunks = [chunk async for chunk in client.stream_chat(_messages())]
    for chunk in chunks[:-1]:
        assert chunk.prompt_tokens is None
        assert chunk.completion_tokens is None
    final = chunks[-1]
    # A provider either reports both counters on the final chunk or reports nothing.
    assert (final.prompt_tokens is None) == (final.completion_tokens is None)


async def test_healthcheck_succeeds(client: LLMClient) -> None:
    # Contract: healthcheck() returns None on success, raises ProviderError on failure.
    result: object = await client.healthcheck()
    assert result is None
