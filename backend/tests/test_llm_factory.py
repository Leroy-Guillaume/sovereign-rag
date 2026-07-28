"""Factory dispatch tests for get_llm_client and the collect() helper.

The real adapters (ollama.py, openai_compat.py, azure.py) are created by later
tasks. These tests pin the factory's dispatch contract by installing stub modules
at the exact import paths the factory must use; they keep passing unchanged once
the real adapters exist, because monkeypatch.setitem(sys.modules, ...) wins over
any previously imported module.
"""

import sys
import types
from collections.abc import AsyncIterator

import pytest

from fakes import FakeLLM, make_settings
from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError
from sovereign_rag.llm import get_llm_client
from sovereign_rag.llm.base import ChatMessage, CompletionChunk, collect


def _install_stub_adapter(
    monkeypatch: pytest.MonkeyPatch, module_name: str, class_name: str
) -> type[object]:
    """Install a stub adapter module so the factory's lazy import resolves to it."""
    module = types.ModuleType(module_name)

    class _StubAdapter:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

    setattr(module, class_name, _StubAdapter)
    monkeypatch.setitem(sys.modules, module_name, module)
    return _StubAdapter


def test_ollama_provider_builds_ollama_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_cls = _install_stub_adapter(monkeypatch, "sovereign_rag.llm.ollama", "OllamaLLM")
    client = get_llm_client(make_settings(llm_provider="ollama"))
    assert isinstance(client, stub_cls)


def test_openai_compatible_provider_builds_openai_compat_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_cls = _install_stub_adapter(
        monkeypatch, "sovereign_rag.llm.openai_compat", "OpenAICompatLLM"
    )
    settings = make_settings(
        llm_provider="openai_compatible",
        openai_compat_base_url="http://localhost:8001/v1",
        openai_compat_api_key="test-key",
        openai_compat_model="mistral-small",
    )
    client = get_llm_client(settings)
    assert isinstance(client, stub_cls)


def test_azure_provider_broken_import_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty module makes `from .azure import AzureOpenAILLM` raise ImportError --
    # the same failure mode as azure-identity missing from the environment.
    monkeypatch.setitem(
        sys.modules,
        "sovereign_rag.llm.azure",
        types.ModuleType("sovereign_rag.llm.azure"),
    )
    settings = make_settings(
        llm_provider="azure_openai",
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_chat_deployment="gpt-4o-mini",
    )
    with pytest.raises(ConfigError) as excinfo:
        get_llm_client(settings)
    assert "uv sync --extra azure" in str(excinfo.value)


async def test_collect_concatenates_deltas_and_returns_final_usage() -> None:
    async def stream() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="Hel")
        yield CompletionChunk(delta="lo")
        yield CompletionChunk(delta="", prompt_tokens=12, completion_tokens=7)

    text, prompt_tokens, completion_tokens = await collect(stream())
    assert text == "Hello"
    assert prompt_tokens == 12
    assert completion_tokens == 7


async def test_collect_returns_none_usage_when_never_reported() -> None:
    async def stream() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="only")

    text, prompt_tokens, completion_tokens = await collect(stream())
    assert text == "only"
    assert prompt_tokens is None
    assert completion_tokens is None


async def test_collect_drains_fake_llm_stream() -> None:
    llm = FakeLLM(chunks=["Hello ", "world"])
    stream = llm.stream_chat([ChatMessage(role="user", content="hi")])
    text, prompt_tokens, completion_tokens = await collect(stream)
    assert text == "Hello world"
    assert prompt_tokens == 10
    assert completion_tokens == 5
