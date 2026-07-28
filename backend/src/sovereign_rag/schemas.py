"""Pydantic response models shared by the HTTP API routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
