"""LLM adapter for the native Ollama API.

Uses the native ``/api/chat`` endpoint, not Ollama's OpenAI-compatible one:
the native API is the only clean way to drive ``think: false`` (disables the
``<think>`` blocks of reasoning models such as qwen3, which would ruin demo
latency) and ``keep_alive`` (keeps the model warm between questions).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from sovereign_rag.config import Settings
from sovereign_rag.errors import ProviderError
from sovereign_rag.llm.base import ChatMessage, CompletionChunk


class OllamaLLM:
    """Streams chat completions from an Ollama server over its native API."""

    model: str

    def __init__(self, settings: Settings) -> None:
        self.model = settings.ollama_model
        self._base_url = settings.ollama_base_url
        self._keep_alive = settings.ollama_keep_alive
        self._think = settings.ollama_think
        self._client = httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=120)

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data: dict[str, Any] = json.loads(line)
                    if data.get("done"):
                        yield CompletionChunk(
                            delta="",
                            prompt_tokens=data.get("prompt_eval_count"),
                            completion_tokens=data.get("eval_count"),
                        )
                        return
                    message: dict[str, Any] = data.get("message") or {}
                    delta = message.get("content", "")
                    if delta:
                        yield CompletionChunk(delta=delta)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Ollama request failed: {exc}. Is Ollama running at {self._base_url}? "
                "Check OLLAMA_BASE_URL, or start the compose 'ollama' profile."
            ) from exc

    async def healthcheck(self) -> None:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Ollama healthcheck failed: {exc}. Is Ollama running at {self._base_url}?"
            ) from exc
