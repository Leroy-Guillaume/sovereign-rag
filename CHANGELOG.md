# Changelog

All notable changes to sovereign-rag. Dates are release dates.

## v0.2.0 - 2026-08-25

The agents era: two measured multi-agent systems, complete OIDC, measured
PII redaction, and a supply chain that proves itself.

### Agents (LangGraph runtime, the project's own clients inside)
- Deep search: a second chat mode runs plan, search, write, verify with
  routed repair and bounded budgets; steps stream live in the UI; a corpus
  that cannot answer exits through the structural abstention. Orchestrator
  model chosen on a tool-calling bench: the 4b instruct matches the larger
  thinking variants at a fraction of the latency.
- Compliance auditor: audit my documents against this regulation. Four
  agents map the regulation, hunt evidence in the caller's other documents
  (ACL enforced), rule compliant / gap / indeterminate with citations, and
  write the summary. Jobs checkpoint per requirement and resume after a
  restart. Ground-truth bench: 6/6 verdicts, full gap recall and compliant
  precision; a real 30-requirement nLPD audit cites evidence across three
  languages.

### Identity and privacy
- OIDC end to end: JWT validation against the operator's own IdP (JWKS
  cache with rotation handling, Keycloak and Entra role shapes) plus the
  SPA login (Authorization Code + PKCE, transparent refresh, sign-out).
  API keys keep working next to it. Verified against a real Keycloak.
- PII redaction at the LLM boundary: everything outbound goes through one
  decorator. Deterministic patterns (emails, phones, IBAN, Swiss AVS) at
  100 % recall and zero false positives; an optional NER tier shaped by a
  seven-arm redaction bench (names 99 %, 2 % clean-text rewrites; full-NER
  redaction measured at 47 % clean-text damage and rejected).

### Governance
- Append-only audit trail (database-enforced) of uploads, deletions,
  sharing changes, exports and audits, readable by admins.
- Self-service conversation export (nLPD art. 25), nothing held back.
- Unanswered questions surface in the admin as an indexing backlog.

### Product
- The whole app speaks EN (default), FR and DE, formats included; the
  landing gained the same three languages earlier.
- Chat export button; deep-search toggle and step timeline.

### Platform and measurement
- CI gains a retrieval smoke gate: the bench replays a cross-lingual slice
  on every push, floors enforced.
- Publishing moved to native arm64 runners: four short builds and a signed
  multi-arch index per image, minutes instead of an emulated hour.
- Optional local MLflow tracking for every bench (retrieval, redaction,
  tool-calling, compliance), zero runtime footprint.

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
