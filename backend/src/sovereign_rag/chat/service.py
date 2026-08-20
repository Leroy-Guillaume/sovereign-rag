"""Chat service: retrieve -> prompt -> stream -> persist.

The assistant message is ALWAYS persisted (finally block), including on
mid-stream provider failures and client disconnects: nothing escapes audit.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..auth import User
from ..config import Settings
from ..embeddings.base import EmbeddingClient
from ..errors import ProviderError
from ..llm.base import ChatMessage, LLMClient
from ..reranking.base import Reranker
from ..store.base import VectorStore
from .prompts import build_messages, hits_to_sources

logger = structlog.get_logger()

HISTORY_LIMIT = 10

_INSERT_CONVERSATION = """
INSERT INTO conversations (user_id, title)
VALUES (%(user_id)s, %(title)s)
RETURNING id
"""

_SELECT_CONVERSATION_OWNER = """
SELECT user_id
FROM conversations
WHERE id = %(id)s
"""

_SELECT_HISTORY = """
SELECT role, content
FROM messages
WHERE conversation_id = %(conversation_id)s
ORDER BY created_at DESC
LIMIT %(limit)s
"""

_INSERT_USER_MESSAGE = """
INSERT INTO messages (conversation_id, request_id, role, content)
VALUES (%(conversation_id)s, %(request_id)s, 'user', %(content)s)
"""

_INSERT_ASSISTANT_MESSAGE = """
INSERT INTO messages (
    id, conversation_id, request_id, role, content, sources, model,
    prompt_tokens, completion_tokens, retrieval_ms, generation_ms, error_code
)
VALUES (
    %(id)s, %(conversation_id)s, %(request_id)s, 'assistant', %(content)s,
    %(sources)s, %(model)s, %(prompt_tokens)s, %(completion_tokens)s,
    %(retrieval_ms)s, %(generation_ms)s, %(error_code)s
)
"""


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One event of the chat stream; the route maps it 1:1 to an SSE frame.

    ``data`` is a JSON-ready dict, except for the ``sources`` event where the
    wire contract requires a JSON array (list of SourceOut-shaped dicts).
    """

    type: Literal["start", "sources", "delta", "done", "error"]
    data: dict[str, Any] | list[dict[str, Any]]


def _current_request_id() -> UUID:
    """Correlation id: reuse the middleware-bound request_id when available."""
    raw = structlog.contextvars.get_contextvars().get("request_id")
    if raw is None:
        return uuid4()
    try:
        return UUID(str(raw))
    except ValueError:
        return uuid4()


class ChatService:
    """Orchestrates retrieval, prompting, LLM streaming and persistence."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        llm: LLMClient,
        embedder: EmbeddingClient,
        store: VectorStore,
        settings: Settings,
        reranker: Reranker | None = None,
    ) -> None:
        self._pool = pool
        self._llm = llm
        self._embedder = embedder
        self._store = store
        self._settings = settings
        self._reranker = reranker

    async def stream_reply(
        self, user: User, conversation_id: UUID | None, message: str
    ) -> AsyncIterator[ChatEvent]:
        """Yield start / sources / delta* / (done | error) for one user turn.

        Raises LookupError before the first yield when the conversation does
        not exist or belongs to another user (the route turns it into a 404).
        The assistant message is persisted in the finally block on EVERY exit
        path: success, provider failure, client disconnect, unexpected error.
        """
        conv_id, history = await self._resolve_conversation(user, conversation_id, message)
        request_id = _current_request_id()
        async with self._pool.connection() as conn:
            await conn.execute(
                _INSERT_USER_MESSAGE,
                {"conversation_id": conv_id, "request_id": request_id, "content": message},
            )

        message_id = uuid4()
        accumulated: list[str] = []
        sources: list[dict[str, Any]] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        retrieval_ms: int | None = None
        generation_ms: int | None = None
        error_code: str | None = None
        generation_started: float | None = None
        finished = False
        try:
            t0 = time.perf_counter()
            query_embedding = await self._embedder.embed_query(message)
            # Recall-then-precision: with a reranker the fused query over-fetches
            # a candidate pool, the cross-encoder re-scores it and keeps top_k.
            pool_k = (
                self._settings.reranker_candidates
                if self._reranker is not None
                else self._settings.retrieval_top_k
            )
            hits = await self._store.hybrid_search(
                message,
                query_embedding,
                user_id=user.id,
                k=pool_k,
            )
            rerank_ms: int | None = None
            if self._reranker is not None:
                t1 = time.perf_counter()
                hits = await self._reranker.rerank(message, hits, k=self._settings.retrieval_top_k)
                rerank_ms = int((time.perf_counter() - t1) * 1000)
            retrieval_ms = int((time.perf_counter() - t0) * 1000)
            # Per-leg contribution: the observability every fusion change is
            # judged against. Cheap: the ranks are already on each hit.
            logger.info(
                "retrieval_legs",
                hits=len(hits),
                vec_only=sum(1 for h in hits if h.fts_rank is None),
                fts_only=sum(1 for h in hits if h.vec_rank is None),
                both=sum(1 for h in hits if h.vec_rank is not None and h.fts_rank is not None),
                documents=len({h.document_id for h in hits}),
                reranked=self._reranker is not None,
                rerank_ms=rerank_ms,
                retrieval_ms=retrieval_ms,
            )
            sources = hits_to_sources(hits)

            yield ChatEvent(type="start", data={"conversation_id": str(conv_id)})
            yield ChatEvent(type="sources", data=sources)

            messages = build_messages(history, message, hits)
            generation_started = time.perf_counter()
            async for chunk in self._llm.stream_chat(messages):
                if chunk.delta:
                    accumulated.append(chunk.delta)
                    yield ChatEvent(type="delta", data={"text": chunk.delta})
                if chunk.prompt_tokens is not None:
                    prompt_tokens = chunk.prompt_tokens
                if chunk.completion_tokens is not None:
                    completion_tokens = chunk.completion_tokens
            generation_ms = int((time.perf_counter() - generation_started) * 1000)
            finished = True
            yield ChatEvent(
                type="done",
                data={
                    "message_id": str(message_id),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "retrieval_ms": retrieval_ms,
                    "generation_ms": generation_ms,
                },
            )
        except ProviderError as exc:
            error_code = "provider_error"
            yield ChatEvent(type="error", data={"code": "provider_error", "detail": str(exc)})
        except (asyncio.CancelledError, GeneratorExit):
            # The client went away mid-stream: the route's cleanup cancels the
            # pending next-event task (CancelledError lands here) or closes the
            # generator (GeneratorExit lands here). Record the partial answer,
            # then let the cancellation propagate.
            if not finished:
                error_code = "client_disconnect"
            raise
        except Exception:
            error_code = "internal_error"
            logger.exception("chat stream failed unexpectedly")
            yield ChatEvent(
                type="error",
                data={"code": "internal_error", "detail": "unexpected server error"},
            )
        finally:
            if generation_ms is None and generation_started is not None:
                generation_ms = int((time.perf_counter() - generation_started) * 1000)
            # Starlette runs this generator under an anyio cancel scope where
            # cancellation is level-triggered: once the client is gone,
            # CancelledError is re-delivered at every await, so an unshielded
            # INSERT could itself be cancelled and the audit row silently lost.
            # The INSERT runs as a shielded task and is waited out to
            # completion before the cancellation is allowed to continue.
            persist = asyncio.get_running_loop().create_task(
                self._persist_assistant_message(
                    {
                        "id": message_id,
                        "conversation_id": conv_id,
                        "request_id": request_id,
                        "content": "".join(accumulated),
                        "sources": Jsonb(sources),
                        "model": f"{self._settings.llm_provider}/{self._llm.model}",
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "retrieval_ms": retrieval_ms,
                        "generation_ms": generation_ms,
                        "error_code": error_code,
                    }
                )
            )
            try:
                await asyncio.shield(persist)
            except asyncio.CancelledError:
                while not persist.done():
                    with contextlib.suppress(BaseException):
                        await asyncio.shield(persist)
                if not persist.cancelled():
                    exc = persist.exception()
                    if exc is not None:
                        logger.error(
                            "assistant message persistence failed during disconnect",
                            error=str(exc),
                        )
                raise

    async def _persist_assistant_message(self, params: dict[str, Any]) -> None:
        """Write the assistant audit row; runs shielded inside stream_reply's finally."""
        async with self._pool.connection() as conn:
            await conn.execute(_INSERT_ASSISTANT_MESSAGE, params)

    async def _resolve_conversation(
        self, user: User, conversation_id: UUID | None, message: str
    ) -> tuple[UUID, list[ChatMessage]]:
        """Create the conversation on first message, or load owner + history."""
        async with self._pool.connection() as conn:
            if conversation_id is None:
                cur = await conn.execute(
                    _INSERT_CONVERSATION, {"user_id": user.id, "title": message[:60]}
                )
                row = await cur.fetchone()
                if row is None:  # pragma: no cover - RETURNING always yields a row
                    raise RuntimeError("conversation INSERT returned no row")
                return row[0], []
            cur = await conn.execute(_SELECT_CONVERSATION_OWNER, {"id": conversation_id})
            row = await cur.fetchone()
            if row is None or row[0] != user.id:
                # Unknown and foreign conversations are indistinguishable on
                # purpose (no existence oracle): the route answers 404 to both.
                raise LookupError("conversation not found")
            cur = await conn.execute(
                _SELECT_HISTORY,
                {"conversation_id": conversation_id, "limit": HISTORY_LIMIT},
            )
            rows = await cur.fetchall()
            history = [ChatMessage(role=role, content=content) for role, content in reversed(rows)]
            return conversation_id, history
