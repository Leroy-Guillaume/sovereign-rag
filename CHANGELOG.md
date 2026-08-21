# Changelog

All notable changes to sovereign-rag. Dates are release dates.

## v0.1.0 - 2026-08-21

First tagged release: the full Phase 1 + Phase 2 scope, measured and shipped.

### Retrieval
- Hybrid retrieval in one SQL round trip: pgvector HNSW cosine leg fused with a
  trilingual (french, german, english) full-text leg through weighted Reciprocal
  Rank Fusion, with informative-term selection, a strict-AND-first / relaxed-OR
  fallback and a per-document cap.
- Optional cross-encoder reranking in-process, `BAAI/bge-reranker-v2-m3` by
  default, chosen on the bench (MRR ladder), with an ONNX export tool.
- Optional `BAAI/bge-m3` (1024d) embedding upgrade via an operator migration;
  `intfloat/multilingual-e5-small` stays the offline default.
- Measured on the public bench (bench/): 96 % hit@8 (153/159), MRR 0.775,
  cross-lingual MRR 0.84, 0 fabricated answers on 16 no-answer trap questions.

### Product
- Streaming chat (SSE) with per-answer source citations; a collapsible sources
  panel shows each passage with fused score and per-leg ranks, and exports the
  audit snapshot as JSON.
- Per-document ACL: uploads private by default, named grants and the `*`
  wildcard, enforced inside every retrieval leg and on the listing surface.
- Admin dashboard: usage, token and latency tiles over a selectable 7/30/90-day
  window, per-document passage counts, drag-and-drop upload, inline sharing.
- Public trilingual landing page (EN default, FR, DE) with an animated product
  demo; Geist fonts self-hosted, zero external calls.

### Platform
- Docker Compose stack (API, frontend, PostgreSQL 16 + pgvector) that runs
  fully offline on the local profile; images published to GHCR on every merge.
- CI: ruff, pyright strict, 200 tests against a real PostgreSQL, Trivy image
  gate, an Azure-free core install check.
- COMPLIANCE.md: ISO/IEC 27001:2022, Swiss nLPD and Geneva LIPAD mapping with
  per-profile data residency.
