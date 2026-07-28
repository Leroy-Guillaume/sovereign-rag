"""LLM adapter for any OpenAI-compatible endpoint (vLLM, Infomaniak AI Tools, Mistral...).

Reference implementation for the CONTRIBUTING walkthrough "add an LLM provider
in 30 minutes": one constructor reading Settings, one async-generator
stream_chat, one healthcheck, and every provider exception wrapped into
ProviderError so callers never see transport details.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import openai
from openai.types.chat import ChatCompletionMessageParam

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError, ProviderError
from sovereign_rag.llm.base import ChatMessage, CompletionChunk


def _to_openai_messages(messages: Sequence[ChatMessage]) -> list[ChatCompletionMessageParam]:
    """Rebuild role-specific typed dicts so pyright can match the SDK union type."""
    converted: list[ChatCompletionMessageParam] = []
    for message in messages:
        if message.role == "system":
            converted.append({"role": "system", "content": message.content})
        elif message.role == "user":
            converted.append({"role": "user", "content": message.content})
        else:
            converted.append({"role": "assistant", "content": message.content})
    return converted


class OpenAICompatLLM:
    """Streams chat completions from any endpoint speaking the OpenAI protocol."""

    model: str

    def __init__(self, settings: Settings) -> None:
        # The Settings validator guarantees these when llm_provider=openai_compatible;
        # the explicit check narrows the Optional types for pyright and guards direct use.
        base_url = settings.openai_compat_base_url
        model = settings.openai_compat_model
        if not base_url or not model:
            raise ConfigError(
                "LLM_PROVIDER=openai_compatible requires OPENAI_COMPAT_BASE_URL "
                "and OPENAI_COMPAT_MODEL"
            )
        self.model = model
        self._base_url = base_url
        api_key = (
            settings.openai_compat_api_key.get_secret_value()
            if settings.openai_compat_api_key
            else "not-needed"  # some local servers (vLLM, Ollama) accept any key
        )
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=_to_openai_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield CompletionChunk(delta=delta)
                if chunk.usage is not None:
                    # Final chunk (include_usage): empty choices, token counts set.
                    yield CompletionChunk(
                        delta="",
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                    )
        except openai.OpenAIError as exc:
            raise ProviderError(
                f"OpenAI-compatible endpoint at {self._base_url} failed: {exc}. "
                "Check OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_API_KEY and OPENAI_COMPAT_MODEL."
            ) from exc

    async def healthcheck(self) -> None:
        try:
            await self._client.models.list()
        except openai.OpenAIError as exc:
            raise ProviderError(
                f"OpenAI-compatible endpoint at {self._base_url} is unreachable: {exc}"
            ) from exc
