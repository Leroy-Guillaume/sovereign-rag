# Evaluation bench

The measurement harness behind every retrieval number this repository cites:
a trilingual legal corpus, stratified golden question sets, and the runners
that score the live stack. Everything here is reproducible; the recorded
numbers live in [results/](results/).

## What it measures, and why strata

A single averaged score hides where a retrieval pipeline actually fails, so
the golden sets are stratified. Each question carries the document it must
retrieve (`expect`, a filename substring), an optional passage marker
(`hint`, a substring the retrieved chunk should contain), and a stratum:

| Stratum | n (v3) | Intent |
|---|---|---|
| S0 | 30 | legacy baseline: direct questions with one clear target document |
| S1 | 23 | citations: "what does Article X say", the answer must come from that article |
| S2 | 42 | paraphrase: real-life phrasing with little or no keyword overlap with the target passage |
| S3 | 27 | rare terms: niche jargon (TIBER-EU, EU-CyCLONe, ...) that lexical search should nail |
| S4 | 15 | cross-lingual: question in one language, target document in another |
| S5 | 22 | multi-hop scenarios: the right document follows only from combining constraints |
| S6 | 16 | no-answer: nothing in the corpus answers this; the correct behavior is an explicit refusal |

`golden_v3.json` (175 questions) is the current set. `golden_v2.json` (129)
is kept because recorded history and past pull requests cite it; new runs
should use v3.

## Metrics

- **hit@k**: share of questions whose expected document appears in the top k
  returned sources. A source counts when `expect` matches its filename and,
  when a `hint` is set, the hint appears in the chunk; a filename-only match
  is accepted as fallback (right document, different passage).
- **MRR**: mean reciprocal rank of the first counted source (1/rank,
  0 when absent from the top 8).
- **Lexical contribution**: share of returned sources that carried a rank in
  the full-text leg of the fusion, a health check that hybrid search is
  actually hybrid.
- **Abstention (S6)**: a trilingual refusal regex over the generated answer,
  deliberately treated as a floor: every non-matching response is printed
  for manual review before anything is called a fabrication.

## Corpus

30 markdown files under [corpus/](corpus/): ten EU legal acts (GDPR, NIS2,
AI Act, Cybersecurity Act, DSA, DMA, Data Act, DORA, eIDAS, and the
regulation on data protection by EU institutions), each in FR, DE and EN,
6.9 MB total. Parallel multilingual legal text is what this project's
retrieval was tuned on: it is dense, self-similar across languages, and full
of near-duplicate chunks, which is exactly what stresses fusion and
reranking.

The default stack also seeds three small demo documents from `data/demo/`
at boot; several golden questions target them (Swiss DPA excerpts, an ISO
27001 overview PDF), so the measured corpus is 33 documents in total.

To rebuild the corpus from source (only needed to refresh it; the files are
committed):

    uv run bench/fetch_corpus.py

## Running the bench

Prerequisites: the compose stack from the repo root, and `uv`.

1. Start the stack and wait for `/healthz`:

       cp .env.example .env
       docker compose up -d --build

2. Ingest the corpus (sequential on purpose; with local CPU embedding this
   is slow, roughly an hour, and concurrent uploads are slower still):

       uv run bench/reingest.py

   Skip this step if the target stack already holds the corpus. The demo
   documents are seeded automatically at boot.

3. Score retrieval (S0-S5; every question goes through `/api/chat`, so LLM
   generation time dominates the wall clock):

       uv run bench/run.py "my label"
       uv run bench/run.py "quick check" --limit 10

4. Score abstention (S6):

       uv run bench/abstention.py

All four scripts are stdlib-only and target the stack through two
environment variables: `SOVEREIGN_RAG_URL` (default `http://localhost:8000`)
and `SOVEREIGN_RAG_API_KEY` (default `sk-demo-admin`).

## SQL-direct tools

Four more scripts bypass the API and query Postgres directly, to isolate
retrieval changes from generation and to replay historical calibrations.
They need the backend environment (for `psycopg`, `sentence-transformers`
and the `sovereign_rag` package) and a database reachable via
`DATABASE_URL` (default `postgresql://rag:rag@localhost:5432/rag`):

    cd backend
    uv run --extra local ../bench/compare.py          # old vs shipped fusion, per stratum
    uv run --extra local ../bench/sweep.py            # fusion variant sweep (inline SQL)
    uv run --extra local ../bench/rerank_eval.py      # reranker on/off, CPU latency
    uv run --extra local ../bench/reranker_ladder.py  # reranker candidates on shared pools

Because they bypass the API they must embed questions themselves, with the
same model the stack used at ingestion: `qembed.py` handles that, defaulting
to `BAAI/bge-m3` (override with `BENCH_EMBED_MODEL`, e.g. set it to
`intfloat/multilingual-e5-small` against a stock stack) and caching
embeddings under `bench/.cache/`.

## Recorded results

Full record in [results/2026-08.md](results/2026-08.md); these are the
numbers the root README and the landing page cite. Headline, full pipeline
(bge-m3 embeddings + bge-reranker-v2-m3) on golden_v3:

| Metric | Value |
|---|---|
| hit@8 | 153/159 (96 %) |
| MRR | 0.775 |
| S4 cross-lingual MRR | 0.84 |
| Abstention (16 no-answer questions) | 15/16 clean refusals, 1 ambiguous, 0 fabrications |

Note that the headline was measured with the `BAAI/bge-m3` embedding
upgrade applied (see the root README); a stock stack with the default
`multilingual-e5-small` scores lower, most visibly on S4.

## Provenance and licensing

The corpus texts are derived from EUR-Lex (automated HTML-to-markdown
conversion; not the authentic versions of the acts, which are those
published in the Official Journal of the European Union).

(c) European Union, 1998-2026. Reuse of EUR-Lex content is authorised under
Commission Decision 2011/833/EU, provided the source is acknowledged. This
directory redistributes excerpts under that decision, with attribution:
every corpus file records its EUR-Lex source URL in its header, and
`fetch_corpus.py` documents how each file was produced.

The golden question sets and the runner scripts are original work of this
repository and are covered by the repository license.

## Redaction bench

`redaction_golden.py` builds `redaction_golden.json`: 240 corpus sentences
with injected synthetic identifiers (names, emails, phones, IBAN, Swiss AVS,
addresses, organisations; FR/DE/EN) plus 120 clean sentences for the
false-positive budget. `redaction_eval.py` measures the engines (the shipped
pattern and NER redactors, full Presidio, a local-LLM arm) on recall per
type, clean-text rewrites and latency:

    uv run bench/redaction_golden.py
    uv run --script bench/redaction_eval.py --engine person-detect

Results and the shipping verdict: `results/2026-08-redaction.md`.
