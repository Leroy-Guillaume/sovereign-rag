# Redaction bench, 2026-08-22

Engines measured on `redaction_golden.json`: 240 cases (real corpus sentences
with 1-3 injected synthetic identifiers, 80 per language) plus 120 clean
corpus sentences for the false-positive budget. Hardware: Apple M4 Max, CPU.
Reproduce: `uv run bench/redaction_golden.py` then
`uv run --script bench/redaction_eval.py --engine <arm>`.

## Results

| Arm | Recall overall | Names | Orgs | Addresses | Direct ids* | Clean rewritten (FP) | ms/case |
|---|---|---|---|---|---|---|---|
| patterns | 50 % | 0 % | 0 % | 0 % | 100 % | **0 %** | ~0 |
| presidio (full NER) | 89 % | 100 % | 100 % | 100 % | 3-100 %** | 47 % | 8 |
| both (patterns + full NER) | 100 % | 100 % | 100 % | 100 % | 100 % | 47 % | 6 |
| person-layered (lang known) | 87 % | 99 % | 33 % | 5 % | 100 % | 1 % | 7 |
| person-union (3-lang union) | 94 % | 99 % | 56 % | 67 % | 100 % | 58 % | 20 |
| **person-detect (shipped as `ner`)** | **87 %** | **99 %** | 33 % | 8 % | **100 %** | **2 %** | **6** |
| llm local (qwen3:4b, n=60) | 95 % | 100 % | 100 % | 100 % | 40-100 %*** | 20 % | 781 |

\* emails, phone numbers, IBAN, Swiss AVS numbers combined.
\** full Presidio does not know the Swiss AVS format (3 %) and misses a third
of IBANs (64 %); its direct-identifier column is not one number.
\*** the local model rewrites long digit strings unreliably: IBAN 40 %.

Language guess (stopword counting, shipped in `guess_language`): 354/360
correct (98 %) on the golden.

## Verdict

- **Full NER is disqualified for this product**: 47 % of clean legal
  sentences get rewritten (law names, institutions, countries flagged as
  entities). A RAG whose value is verbatim citation cannot ship that. The
  3-language union is worse still (58 %): cross-language NER sees persons
  everywhere.
- **`REDACTION_PROVIDER=patterns`** stays the recommendation when only
  direct identifiers matter: 100 % on all four types, zero false positives,
  zero cost, zero dependencies.
- **`REDACTION_PROVIDER=ner`** (patterns + PERSON-only NER in the guessed
  language) is the measured upgrade when person names must not leave:
  names 99 %, direct identifiers 100 %, 2 % false positives, 6 ms. The
  accepted trade, in numbers: organisations 33 % and addresses 8 % stay
  unmasked, because catching them is exactly what triggers the 47 %
  false-positive regime.
- The local-LLM arm stays exploratory: best semantic coverage but 781 ms
  per text, 20 % clean rewrites, and unreliable digit handling.
