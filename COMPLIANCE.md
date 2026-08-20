# Compliance

**Audience:** CIO / CISO (DSI / RSSI) evaluating sovereign-rag for deployment in a Swiss or
European organization.

This document maps sovereign-rag, **as shipped in Phase 1**, to the frameworks that matter in
that context: data residency per deployment profile, ISO/IEC 27001:2022 Annex A, the Swiss
Federal Act on Data Protection (nLPD / FADP), and the Geneva LIPAD. It is deliberately honest:
every control that is not implemented yet is tagged **Roadmap** with its phase. Nothing in this
document claims a feature that the code does not have today.

## 1. Deployment profiles

**Local profile** (default: `LLM_PROVIDER=ollama`, `EMBEDDING_PROVIDER=local`,
`VECTOR_STORE=pgvector`). Every component runs on hosts you control: the LLM is served by
Ollama, embeddings are computed by a sentence-transformers model inside the API container, and
all data (documents, chunks, vectors, conversations) lives in your PostgreSQL instance. After
the one-time Ollama model pull (the embedding weights are already baked into the API image at
build time), the application makes no outbound network call in this profile (the image sets
`HF_HUB_OFFLINE=1`, so not even a model-freshness check leaves the container). This is the
profile to choose when documents or prompts must never leave your infrastructure.

**OpenAI-compatible profile** (`LLM_PROVIDER=openai_compatible`). The LLM is any endpoint that
speaks the OpenAI Chat Completions API: a vLLM server in your own datacenter, a Swiss-hosted
provider such as Infomaniak AI Tools, Mistral's platform, or any other. Prompts and the
document passages retrieved for each question transit to the endpoint **you** configured, and
you choose the operator, the contract, and the jurisdiction. Embeddings stay local by default
(`EMBEDDING_PROVIDER=local`), so raw chunk text is not sent out for indexing.

**Azure profile** (`LLM_PROVIDER=azure_openai`, optionally `EMBEDDING_PROVIDER=azure_openai`).
Inference runs on Azure OpenAI in the Azure region you select (e.g. Switzerland North).
Microsoft's data-processing commitment for Azure OpenAI applies: your prompts and completions
are not used to train foundation models, and are processed within the service boundary you
provisioned. See [Data, privacy, and security for Azure OpenAI
Service](https://learn.microsoft.com/en-us/legal/cognitive-services/openai/data-privacy).
API-key access works out of the box; keyless access via managed identity uses the optional
`azure` extra (`uv sync --extra azure`).

## 2. Data residency matrix

Where each category of data lives in each profile, and which third party (if any) can see it.
The same information is annotated variable-by-variable in `.env.example`
(`# data leaves your infra: yes/no`).

| Data | Local profile | OpenAI-compatible profile | Azure profile |
|---|---|---|---|
| User prompts | Stored in your PostgreSQL; processed by Ollama on your host. **Never leaves your infrastructure.** | Stored in your PostgreSQL. The prompt and the retrieved passages transit to the endpoint you configured, and you choose the operator and the jurisdiction. | Stored in your PostgreSQL. Prompt and retrieved passages are sent to Azure OpenAI in your selected region (use a regional, non-global deployment type); Microsoft does not train models on your data ([commitment](https://learn.microsoft.com/en-us/legal/cognitive-services/openai/data-privacy)). |
| Uploaded documents and chunks | Your PostgreSQL only. Never leaves your host. | Your PostgreSQL. Full documents never leave; only the passages retrieved for a given question are embedded in prompts sent to the endpoint. | Your PostgreSQL. Same: only retrieved passages leave, inside prompts to Azure OpenAI in your region. |
| Embedding vectors | Computed inside the API container (CPU); stored in your PostgreSQL. No third party. | Computed locally by default (`EMBEDDING_PROVIDER=local`); stored in your PostgreSQL. Nothing transits for indexing. | With `EMBEDDING_PROVIDER=azure_openai`, chunk and query text transit to your Azure embeddings deployment; the resulting vectors are stored in your PostgreSQL. |
| LLM inference | Ollama on your host. No third party. | At the endpoint you configured; its operator sees prompts and produces completions under your contract with them. | Azure OpenAI in the region you selected, processed by Microsoft under Azure data-processing terms. |
| Conversation history | Your PostgreSQL. Never leaves your host. | Your PostgreSQL. Only the rolling window (last 10 messages) is included in prompts sent to the endpoint. | Your PostgreSQL. Same rolling-window caveat for prompts sent to Azure OpenAI. |
| Application logs | Structured logs on container stdout, on your host (JSON in `prod`, human-readable console in `dev`). The application ships logs nowhere. | Same: log shipping, if any, is your platform's decision, not the application's. | Same. |
| Model weights | Embedding model baked into the API image at build time; LLM weights in a local Ollama volume. Fully offline after the first pull. | Hosted by the endpoint operator; they see nothing beyond the prompts you send. | Hosted by Microsoft; not trained on your data per the commitment above. |

## 3. ISO/IEC 27001:2022 Annex A mapping

Control references use the standard's publicly available control titles; no text from the body
of the standard is reproduced.

| Control | Theme | How sovereign-rag addresses it | Status |
|---|---|---|---|
| A.5.15 | Access control | Every API route requires an API key mapped to a stable user id (`AUTH_API_KEYS`); only the liveness/readiness probes are anonymous. In `prod` the application refuses to boot with an empty key set. Per-document ACL is enforced: uploads are private to their owner, sharing is explicit (`document_permissions`, a named user or the `*` wildcard), and the same predicate is applied inside each retrieval leg before fusion and on the listing surface. Two-principal leakage tests run against both store implementations. | Implemented (Phase 1 + Phase 2 ACL) |
| A.5.18 | Access rights | Admin rights are granted explicitly via `AUTH_ADMIN_USERS`; document deletion is restricted to the uploader or an admin. Identity lifecycle via OIDC, then Entra ID. | Implemented (Phase 1); OIDC Roadmap (Phase 2), Entra ID Roadmap (Phase 4) |
| A.5.28 | Collection of evidence | Every assistant message persists an immutable snapshot of the sources shown to the user (filename, section/page, excerpt, score, per-leg ranks) that **survives document deletion**, plus a `request_id` correlation key. Persistence runs in a `finally` block shielded from cancellation, so the audit row lands on every exit path: success, provider failure, even a client disconnect mid-answer (`error_code` records the cause). A dedicated append-only `audit_log` table is scheduled. | Implemented (Phase 1); audit_log Roadmap (Phase 2) |
| A.8.9 | Configuration management | `.env` is the single source of runtime configuration; a CI-enforced test (`backend/tests/test_env_example.py`) asserts `.env.example` covers every `Settings` field, so documentation cannot drift from code. Embedding model and dimensions are frozen: a boot-time check against the `embedding_config` table refuses to start on mismatch, preventing silent index invalidation. | Implemented (Phase 1) |
| A.8.12 | Data leakage prevention | The local profile is structural DLP: no outbound data path exists. Every provider block in `.env.example` is annotated `# data leaves your infra: yes/no`. A `redact()` seam already exists in the prompt builder for PII redaction (Presidio). | Implemented (Phase 1, structural); PII redaction Roadmap (Phase 2) |
| A.8.15 | Logging | Structured logging (structlog); a per-request `request_id` is generated by middleware, bound to every log line, and persisted with each message for end-to-end correlation. Consolidated export is scheduled (Phase 2). | Implemented (Phase 1); export Roadmap (Phase 2) |
| A.8.16 | Monitoring activities | `/healthz` (liveness, no dependencies) and `/readyz` (database ping + LLM and embeddings healthchecks, cached 10 s); Docker HEALTHCHECKs on every service. Metrics dashboard built on the typed per-message columns. | Implemented (Phase 1); dashboard Roadmap (Phase 2) |
| A.8.24 | Use of cryptography | Operator guidance: terminate TLS at your reverse proxy or ingress in front of the frontend/API; encrypt PostgreSQL at rest via platform disk encryption (LUKS, cloud-managed keys). In the application: API keys are compared in constant time (`secrets.compare_digest`, iterating every configured key with no early exit); no secret is ever committed or logged. | Implemented (Phase 1) + operator guidance |
| A.8.25-A.8.31 | Secure development lifecycle | CI gates on every push to main and every pull request: ruff lint and format check, pyright strict type checking, test coverage ≥ 80 %, integration tests against a real PostgreSQL service container, a Trivy scan of both images failing on CRITICAL/HIGH findings, a dedicated job proving the core installs and boots without Azure SDKs, multi-stage non-root images, and **zero cloud secrets in the pipeline** (all providers are faked in tests). | Implemented (Phase 1) |

**Note on Row-Level Security.** Phase 2 access control is enforced as an explicit SQL predicate
applied inside each retrieval leg: visible, unit-testable with two-principal leakage tests, and
explainable to a non-PostgreSQL auditor. Operators who additionally want database-level
enforcement can enable PostgreSQL RLS on top of it as optional defense in depth; the application
does not require it.

## 4. Swiss nLPD (FADP) mapping

The applicable text is the Federal Act on Data Protection of 25 September 2020 (SR 235.1),
official versions at [fedlex.admin.ch/eli/cc/2022/491/fr](https://www.fedlex.admin.ch/eli/cc/2022/491/fr)
(FR) and [fedlex.admin.ch/eli/cc/2022/491/de](https://www.fedlex.admin.ch/eli/cc/2022/491/de)
(DE); an English translation is published on the same fedlex page. Excerpts of the official FR
and DE texts ship in the demo corpus (see section 7).

| Provision | Requirement | How sovereign-rag addresses it |
|---|---|---|
| Art. 6 | Lawfulness, good faith, proportionality | Retrieval is scoped strictly to the corpus the operator chose to ingest; the system prompt instructs the model to answer **only** from retrieved context and to state explicitly when no relevant passage was found. Data is processed for the answering purpose only, with no secondary use. |
| Art. 7 | Privacy by design and by default | The defaults are local-first (`LLM_PROVIDER=ollama`, `EMBEDDING_PROVIDER=local`): with zero configuration, no data leaves your infrastructure. Any cloud egress is opt-in, requires explicit configuration, and is flagged in `.env.example`. |
| Art. 8 | Data security | Authenticated API with constant-time key comparison, non-root containers, pinned dependencies (`uv.lock`, `package-lock.json`, frozen builds), image vulnerability gate in CI (Trivy), TLS termination guidance for operators (section 3, A.8.24). |
| Art. 19-21 | Duty to inform | Operator guidance: inform your users that their prompts and conversation history are stored in your database, and, in the OpenAI-compatible and Azure profiles, name the processor that receives prompts (the endpoint operator or Microsoft) in your privacy notice. |
| Art. 25 | Right of access | Each user can retrieve their own conversation history through the API (`GET /api/conversations` and `GET /api/conversations/{id}` return only the requester's conversations). A self-service export endpoint is Roadmap (Phase 2). |

## 5. Geneva LIPAD note

For Geneva public institutions subject to the LIPAD (rs/GE A 2 08, official consolidated text in
the Geneva systematic legislation collection at [silgeneve.ch/legis](https://silgeneve.ch/legis)),
two properties matter. First, the local profile keeps documents, prompts, and conversation
history entirely inside the institution: no processor outside your walls is involved at any
point. Second, every answer is source-cited: each assistant message stores a snapshot of the
exact excerpts shown to the user, with document name, section or page, and retrieval scores, and
this snapshot survives later deletion of the document. The snapshot is written on every exit
path, including when the user aborts mid-answer or the provider fails mid-stream, because
persistence is shielded from the disconnect itself. This supports transparency and
document-based accountability obligations: you can always reconstruct what the system showed,
based on which official document, and when.

## 6. Container and supply-chain security

- **Multi-stage builds, slim non-root images.** The API image builds with uv in a builder stage
  and runs on `python:3.12-slim` as a dedicated non-root user (uid 1000); the frontend serves
  its static build from `nginxinc/nginx-unprivileged` (uid 101, port 8080, no root anywhere).
- **Offline by construction.** The embedding model and the reranker cross-encoder are baked
  into API image layers at build time (`HF_HOME`), so the container never contacts Hugging Face
  at runtime. The cost is an API image of roughly 3 GB (CPU-only torch wheels plus the two
  models); the frontend image is under 50 MB.
- **Vulnerability gate.** Trivy scans both images in CI and fails the pipeline on any CRITICAL
  or HIGH finding with an available fix (`ignore-unfixed`).
- **Pinned dependencies.** `uv.lock` (backend) and `package-lock.json` (frontend) are committed;
  builds use frozen resolution (`uv sync --frozen`, `npm ci`).
- **No cloud secrets in CI.** The pipeline needs no provider credentials: LLM and embedding
  providers are faked in tests, and the database is an ephemeral `pgvector/pgvector:pg16`
  service container. The same property holds locally: no provider credential exists anywhere
  in the development loop.
- **No shell utilities added for probes.** The API image's Docker HEALTHCHECK runs
  `python -m sovereign_rag.healthcheck` (a local HTTP probe over httpx, already a core
  dependency) instead of installing curl or wget; the frontend probe uses the busybox `wget`
  already present in its Alpine base image, so nothing is added to either image for probing.

## 7. Demo corpus licensing and provenance

The seeded demo corpus (`data/demo/`) is deliberately clean from a licensing standpoint:

- **Swiss legal texts.** `nlpd-excerpt.fr.md` and `dsg-auszug.de.md` are excerpts of the
  official FR and DE versions of the FADP (SR 235.1), fetched from
  [fedlex.admin.ch](https://www.fedlex.admin.ch/eli/cc/2022/491/fr). Official Swiss legal texts
  are not protected by copyright (art. 5 of the Swiss Copyright Act, CopA). Each file header
  records the source URL, the consolidation state, and the fetch date.
- **ISO/IEC 27001 overview.** `iso27001-overview.en.pdf` is an original educational overview
  written for this corpus. ISO/IEC 27001:2022 itself is a copyrighted standard; the document,
  like this compliance mapping, reproduces none of its text and describes publicly known
  concepts in its authors' own words.

## 8. Honest limitations (Phase 1)

Phase 1 is a working, auditable baseline, not the finished compliance story. The gaps below are
known, deliberate, and scheduled. Do not deploy Phase 1 outside a trusted user group without
reading this table.

| Gap in Phase 1 | Consequence | Planned |
|---|---|---|
| Content-hash existence oracle | The sha256 dedupe answers 409 when identical bytes were already ingested by a document the requester cannot see: uploaders can probe whether a known file exists in the corpus. Accepted at pilot scale; per-owner dedupe is the documented evolution. | Accepted trade-off (see ARCHITECTURE 3.10) |
| No audit log export | Evidence is limited to per-message source snapshots and structured logs; there is no consolidated, exportable audit trail. | Roadmap (Phase 2): append-only `audit_log` + export |
| No PII redaction | In cloud profiles, prompts sent to the endpoint may contain personal data present in your documents. The `redact()` seam exists but is a no-op. | Roadmap (Phase 2): Presidio behind the existing seam |
| API-key auth; the frontend stores the key in browser `localStorage` | Demo-grade session security: an XSS flaw in the frontend would expose the key. Acceptable for a pilot behind your perimeter, not for production identity. | Roadmap (Phase 2): OIDC; Roadmap (Phase 4): Entra ID |
| No self-service data export | FADP art. 25 access is served by API queries, not by a one-click export. | Roadmap (Phase 2) |
| No OCR | Scanned PDFs without a text layer fail ingestion with an explicit error message. | Out of scope (documented in the README) |
