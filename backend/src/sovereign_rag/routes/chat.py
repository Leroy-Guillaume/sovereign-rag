"""Chat routes: SSE streaming chat, conversation history, current identity.

Pure HTTP layer: request validation, service invocation, SSE wire formatting.
Wire format: an 'event: <type>' line and a 'data: <json>' line followed by a
blank line; a ': ping' comment line is sent after every 15 s of LLM silence so
proxies and load balancers keep the connection open.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import AsyncGeneratorType
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..audit import audit
from ..auth import CurrentUser
from ..chat.service import ChatEvent, ChatService
from ..schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationExport,
    ConversationOut,
    MessageExport,
    MessageOut,
)

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

# The export carries the FULL persisted record, audit columns included:
# the point of a right-of-access export is that nothing is held back.
_SELECT_MESSAGES_FULL = """
SELECT id, request_id, role, content, sources, model, prompt_tokens,
       completion_tokens, retrieval_ms, generation_ms, error_code, created_at
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
        if task is not None:
            task.cancel()
            # A bare `await task` would itself be cancelled here (client gone
            # means the request scope re-delivers CancelledError at every
            # await), leaving the service generator mid-flight and a later
            # aclose() raising "aclose(): asynchronous generator is already
            # running". Shield and re-await until the drain really finished:
            # the service persistence finally has then run to completion.
            while not task.done():
                with contextlib.suppress(BaseException):
                    await asyncio.shield(task)
            if not task.cancelled():
                task.exception()  # retrieved; the service already persisted and reported
        if isinstance(events, AsyncGeneratorType) and not events.ag_running:
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


@router.get("/api/conversations", response_model=list[ConversationOut])
async def list_conversations(request: Request, user: CurrentUser) -> list[ConversationOut]:
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_SELECT_CONVERSATIONS, {"user_id": user.id})
        rows = await cur.fetchall()
    return [ConversationOut(id=row[0], title=row[1], created_at=row[2]) for row in rows]


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID, request: Request, user: CurrentUser
) -> ConversationDetail:
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_SELECT_CONVERSATION, {"id": conversation_id, "user_id": user.id})
        conversation = await cur.fetchone()
        if conversation is None:
            # Foreign and unknown conversations both answer 404: no existence oracle.
            raise HTTPException(status_code=404, detail="Conversation not found")
        cur = await conn.execute(_SELECT_MESSAGES, {"conversation_id": conversation_id})
        rows = await cur.fetchall()
    return ConversationDetail(
        id=conversation[0],
        title=conversation[1],
        created_at=conversation[2],
        messages=[
            # sources is the persisted jsonb snapshot: SourceOut-shaped dicts with
            # UUIDs as strings, which pydantic coerces back to UUID on validation.
            MessageOut(
                id=row[0],
                role=row[1],
                content=row[2],
                sources=row[3],
                model=row[4],
                created_at=row[5],
            )
            for row in rows
        ],
    )


@router.get("/api/auth/config")
async def auth_config(request: Request) -> dict[str, object]:
    """Public login configuration for the SPA (no secrets: issuer and client
    id are what any OIDC redirect exposes anyway). Anonymous on purpose: the
    login screen needs it before any credential exists."""
    settings = request.app.state.settings
    if settings.oidc_issuer and settings.oidc_client_id:
        return {
            "oidc": {
                "issuer": settings.oidc_issuer.rstrip("/"),
                "client_id": settings.oidc_client_id,
            }
        }
    return {"oidc": None}


@router.get("/api/me")
async def get_me(user: CurrentUser) -> dict[str, Any]:
    return {"id": user.id, "roles": sorted(user.roles)}


@router.get("/api/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: UUID, request: Request, user: CurrentUser
) -> JSONResponse:
    """The conversation as one downloadable JSON document (nLPD art. 25).

    Same visibility rule as the detail route: foreign and unknown ids both
    answer 404. The payload is the full persisted record of every message,
    source snapshots and audit columns included.
    """
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_SELECT_CONVERSATION, {"id": conversation_id, "user_id": user.id})
        conversation = await cur.fetchone()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        cur = await conn.execute(_SELECT_MESSAGES_FULL, {"conversation_id": conversation_id})
        rows = await cur.fetchall()
        await audit(
            conn,
            actor=user.id,
            action="conversation.export",
            object_type="conversation",
            object_id=str(conversation_id),
            detail={"messages": len(rows)},
        )
    export = ConversationExport(
        exported_at=datetime.now(tz=UTC),
        conversation=ConversationOut(
            id=conversation[0], title=conversation[1], created_at=conversation[2]
        ),
        messages=[
            MessageExport(
                id=row[0],
                request_id=row[1],
                role=row[2],
                content=row[3],
                sources=row[4],
                model=row[5],
                prompt_tokens=row[6],
                completion_tokens=row[7],
                retrieval_ms=row[8],
                generation_ms=row[9],
                error_code=row[10],
                created_at=row[11],
            )
            for row in rows
        ],
    )
    filename = f"conversation-{str(conversation_id)[:8]}.json"
    return JSONResponse(
        content=export.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
