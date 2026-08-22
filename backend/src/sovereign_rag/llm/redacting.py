"""Outbound PII boundary: a decorator over any LLMClient.

Redaction is enforced HERE, not in the prompt builder, so that everything
that travels to the provider goes through one choke point: the user's
question, the conversation history and the retrieved passages alike. A
future call site cannot forget to redact; wrapping the client is the only
way to reach the provider.
"""

from collections.abc import AsyncIterator, Callable, Sequence

from .base import ChatMessage, CompletionChunk, LLMClient


class RedactingLLMClient:
    """Masks every outbound message content with the configured redactor.

    Inbound chunks pass through untouched: the provider's answer comes back
    into the infrastructure, it does not leave it.
    """

    def __init__(self, inner: LLMClient, redact: Callable[[str], str]) -> None:
        self._inner = inner
        self._redact = redact
        self.model = inner.model

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        masked = [
            ChatMessage(role=message.role, content=self._redact(message.content))
            for message in messages
        ]
        return self._inner.stream_chat(masked, temperature=temperature, max_tokens=max_tokens)

    async def healthcheck(self) -> None:
        await self._inner.healthcheck()
