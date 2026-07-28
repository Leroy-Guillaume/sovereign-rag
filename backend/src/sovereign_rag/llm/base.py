"""LLM client contract: message/chunk value types and the streaming Protocol."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    delta: str  # text fragment ("" on the final chunk)
    prompt_tokens: int | None = None  # set on the final chunk only
    completion_tokens: int | None = None


class LLMClient(Protocol):
    """Contract: stream_chat yields >=1 chunk and always terminates with a final
    chunk carrying token counts when the provider reports them. Network/provider
    failures raise ProviderError (httpx/openai exceptions never leak)."""

    model: str  # e.g. "qwen3:4b" -- persisted as "{provider}/{model}"

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        """Plain `def` returning AsyncIterator: the exact type of an async
        generator function, which is what every implementation is."""
        ...

    async def healthcheck(self) -> None: ...  # raises ProviderError -- used by /readyz


async def collect(
    stream: AsyncIterator[CompletionChunk],
) -> tuple[str, int | None, int | None]:
    """Drain a stream into (text, prompt_tokens, completion_tokens)."""
    parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    async for chunk in stream:
        parts.append(chunk.delta)
        if chunk.prompt_tokens is not None:
            prompt_tokens = chunk.prompt_tokens
        if chunk.completion_tokens is not None:
            completion_tokens = chunk.completion_tokens
    return "".join(parts), prompt_tokens, completion_tokens
