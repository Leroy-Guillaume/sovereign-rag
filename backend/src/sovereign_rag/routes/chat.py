"""Chat routes: SSE streaming chat, conversation history, current identity.

Pure HTTP layer: request validation, service invocation, SSE wire formatting.
Wire format: an 'event: <type>' line and a 'data: <json>' line followed by a
blank line; a ': ping' comment line is sent after every 15 s of LLM silence so
proxies and load balancers keep the connection open.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..auth import CurrentUser
from ..chat.service import ChatEvent, ChatService
from ..schemas import ChatRequest

router = APIRouter()

PING_INTERVAL_S = 15.0

_SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}

_SELECT_CONVERSATIONS = """
SELECT id, title, created_at
FROM conversations
WHERE user_id = %(user_id)s
ORDER BY created_at DESC
"""

_SELECT_CONVERSATION = """
SELECT id, title, created_at
FROM conversations
WHERE id = %(id)s AND user_id = %(user_id)s
"""

_SELECT_MESSAGES = """
SELECT id, role, content, sources, model, created_at
FROM messages
WHERE conversation_id = %(conversation_id)s
ORDER BY created_at
"""


def _chat_service(request: Request) -> ChatService:
    """Return the single ChatService built by the composition root (main.py lifespan).

    The route never constructs a service: dependencies are wired once at boot and
    live on ``app.state`` (``app.state.chat``). The local annotation is there
    because Starlette's ``State`` is untyped (``Any``) under pyright strict.
    """
    service: ChatService = request.app.state.chat
    return service


def _format_event(event: ChatEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"


async def _next_event(events: AsyncIterator[ChatEvent]) -> ChatEvent | None:
    try:
        return await anext(events)
    except StopAsyncIteration:
        return None


async def _sse_body(first: ChatEvent, events: AsyncIterator[ChatEvent]) -> AsyncIterator[str]:
    """Wrap service events into SSE frames, pinging after 15 s of silence.

    The loop drains the service generator to exhaustion (it stops by itself
    after done/error) so that its finally block - assistant message
    persistence - always runs before the response ends. On cancellation
    (client disconnect) the pending next-event task is cancelled and awaited:
    the service persists the partial answer before the connection tears down.
    """
    task: asyncio.Task[ChatEvent | None] | None = None
    try:
        yield _format_event(first)
        while True:
            task = asyncio.create_task(_next_event(events))
            while True:
                done, _pending = await asyncio.wait({task}, timeout=PING_INTERVAL_S)
                if done:
                    break
                yield ": ping\n\n"
            event = task.result()
            task = None
            if event is None:
                return
            yield _format_event(event)
    finally:
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        if isinstance(events, AsyncGenerator):
            await events.aclose()


@router.post("/api/chat")
async def post_chat(request: Request, body: ChatRequest, user: CurrentUser) -> StreamingResponse:
    service = _chat_service(request)
    events = service.stream_reply(user, body.conversation_id, body.message)
    try:
        first = await anext(events)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found") from None
    return StreamingResponse(
        _sse_body(first, events),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/api/conversations")
async def list_conversations(request: Request, user: CurrentUser) -> list[dict[str, Any]]:
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_SELECT_CONVERSATIONS, {"user_id": user.id})
        rows = await cur.fetchall()
    return [{"id": str(row[0]), "title": row[1], "created_at": row[2].isoformat()} for row in rows]


@router.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, request: Request, user: CurrentUser
) -> dict[str, Any]:
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_SELECT_CONVERSATION, {"id": conversation_id, "user_id": user.id})
        conversation = await cur.fetchone()
        if conversation is None:
            # Foreign and unknown conversations both answer 404: no existence oracle.
            raise HTTPException(status_code=404, detail="Conversation not found")
        cur = await conn.execute(_SELECT_MESSAGES, {"conversation_id": conversation_id})
        rows = await cur.fetchall()
    return {
        "id": str(conversation[0]),
        "title": conversation[1],
        "created_at": conversation[2].isoformat(),
        "messages": [
            {
                "id": str(row[0]),
                "role": row[1],
                "content": row[2],
                "sources": row[3],
                "model": row[4],
                "created_at": row[5].isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/api/me")
async def get_me(user: CurrentUser) -> dict[str, Any]:
    return {"id": user.id, "roles": sorted(user.roles)}
