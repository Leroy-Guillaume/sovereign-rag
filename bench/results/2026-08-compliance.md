# Compliance auditor bench, 2026-08-25

Ground-truth setting, built so the truth is known by construction: a
synthetic six-article regulation (security, breach notification, DPO,
processing register, impact assessment, international transfers) audited
against two internal documents: a security policy deliberately covering
articles 1, 2 and 4, and a noise document (a remote-work charter) covering
nothing. Expected verdicts: compliant on 1/2/4, gap on 3/5/6.

Pipeline under test: the real API and graph (cartographer, investigator,
evaluator, reporter), local qwen3:4b-instruct, e5-small embeddings, no
reranker. Reproduce: `uv run bench/compliance_eval.py` against a stack
with the audits API. Runs recorded in the local MLflow store
(experiment `compliance`).

## Results

| Metric | Score |
|---|---|
| Requirements mapped (6 injected) | 6/6 |
| Verdict accuracy | 6/6 |
| Gap recall (missed gap = the costly error) | 3/3 |
| Compliant precision (false compliant = the dangerous error) | 3/3 |
| End-to-end time (map + 6 assessments + summary) | 10-20 s |

Two independent runs, identical verdicts.

## Honest scope

This setting is deliberately unambiguous: it validates the plumbing
(mapping, ACL-scoped evidence hunt, self-exclusion of the regulation,
per-requirement checkpointing) and the judge on clear-cut cases. It does
NOT yet measure partial coverage, contradictory documents, or cross-lingual
regulation-vs-policy pairs; those harder strata are the natural next
extension before any stronger claim is made.
