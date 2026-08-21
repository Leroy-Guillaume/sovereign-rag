"""Pydantic response models shared by the HTTP API routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PermissionIn(BaseModel):
    """Grant request: a user_id, or '*' for every authenticated user."""

    # No whitespace and no '/': the revoke route carries the principal as a
    # path segment, so a slash would make the grant irrevocable over the API.
    principal: str = Field(min_length=1, max_length=200, pattern=r"^[^\s/]+$")


class PermissionOut(BaseModel):
    principal: str
    granted_by: str
    granted_at: datetime


class LatencyOut(BaseModel):
    """Stage latency percentiles in milliseconds; None until data exists."""

    p50_ms: int | None
    p95_ms: int | None


class CitedDocument(BaseModel):
    filename: str
    citations: int


class AdminMetricsOut(BaseModel):
    """Aggregates over the typed per-message columns (ADR 3.12)."""

    window_days: int
    answers: int
    conversations: int
    prompt_tokens: int
    completion_tokens: int
    errors: int
    retrieval: LatencyOut
    generation: LatencyOut
    top_cited: list[CitedDocument]


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None = None
    owner_id: str
    created_at: datetime
    deduplicated: bool | None = None  # set on POST /api/documents responses only


class SourceOut(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    section: str | None = None
    page: int | None = None
    excerpt: str  # chunk content truncated to 500 chars
    score: float
    vec_rank: int | None = None
    fts_rank: int | None = None


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    sources: list[SourceOut]
    model: str | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime


class ConversationDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    messages: list[MessageOut]


class ChatRequest(BaseModel):
    """POST /api/chat request body."""

    conversation_id: UUID | None = None
    # Bounded: an unbounded message reaches the embedding truncation fine but
    # blows up the lexical tokenizer and the tsquery builder downstream, and
    # nothing useful fits a question beyond this anyway.
    message: str = Field(min_length=1, max_length=8000)
