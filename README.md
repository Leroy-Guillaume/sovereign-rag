# sovereign-rag

A self-hosted RAG template for organizations whose data must not leave their infrastructure.
Hybrid retrieval (pgvector + Postgres full-text search, RRF fusion) with streaming chat and
auditable citations. Swappable LLM and embedding providers: fully local by default (Ollama),
Azure OpenAI when policy allows.

> **Status: Phase 1 in progress** — the full README (quickstart, provider matrix, architecture
> diagram) ships at the end of Phase 1.
