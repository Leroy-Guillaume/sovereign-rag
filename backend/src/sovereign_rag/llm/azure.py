"""LLM adapter for Azure OpenAI.

Transport is the ``openai`` SDK (``AsyncAzureOpenAI``) — not an Azure SDK.
API-key auth works with the core dependencies alone; keyless auth (managed
identity, ``az login``) needs ``azure-identity``, imported lazily below so the
default install profile never loads any ``azure*`` module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import openai
from openai.types.chat import ChatCompletionMessageParam

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError, ProviderError
from sovereign_rag.llm.base import ChatMessage, CompletionChunk

_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


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


class AzureOpenAILLM:
    """Streams chat completions from an Azure OpenAI deployment."""

    model: str  # the deployment name — what Azure routes requests on

    def __init__(self, settings: Settings) -> None:
        # The Settings validator guarantees these when llm_provider=azure_openai;
        # the explicit check narrows the Optional types for pyright and guards direct use.
        endpoint = settings.azure_openai_endpoint
        deployment = settings.azure_openai_chat_deployment
        if not endpoint or not deployment:
            raise ConfigError(
                "LLM_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_CHAT_DEPLOYMENT"
            )
        self.model = deployment
        self._endpoint = endpoint
        if settings.azure_openai_api_key is not None:
            self._client = openai.AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=settings.azure_openai_api_version,
                api_key=settings.azure_openai_api_key.get_secret_value(),
            )
        else:
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            except ImportError as exc:  # azure-identity lives behind the "azure" extra
                raise ConfigError(
                    "AZURE_OPENAI_API_KEY is not set, so keyless auth requires "
                    "azure-identity. Install it with: uv sync --extra azure"
                ) from exc
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), _TOKEN_SCOPE)
            self._client = openai.AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=settings.azure_openai_api_version,
                azure_ad_token_provider=token_provider,
            )

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
                f"Azure OpenAI deployment '{self.model}' at {self._endpoint} failed: {exc}. "
                "Check AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and "
                "AZURE_OPENAI_CHAT_DEPLOYMENT."
            ) from exc

    async def healthcheck(self) -> None:
        try:
            await self._client.models.list()
        except openai.OpenAIError as exc:
            raise ProviderError(
                f"Azure OpenAI endpoint {self._endpoint} is unreachable: {exc}"
            ) from exc
