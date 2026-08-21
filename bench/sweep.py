"""Sweep fusion variants in direct SQL, without LLM generation.

Historical calibration tool: it replays the two-leg fusion (vector + FTS)
with AND vs OR tsqueries and a range of lexical weights, then a three-leg
variant (vector + strict FTS + relaxed OR recall net). This is the sweep
that motivated the shipped strict/relaxed fusion; it keeps its own inline
SQL on purpose so past variants stay comparable.

Needs direct database access and a local embedding model matching the
stack's EMBEDDING_MODEL (see qembed.py).

Environment:
  DATABASE_URL  Postgres DSN (default postgresql://rag:rag@localhost:5432/rag)

Usage: cd backend && uv run --extra local ../bench/sweep.py [--golden PATH]
"""

import argparse
import json
import os
import pathlib

import psycopg
from qembed import as_pgvector, load_qembs

HERE = pathlib.Path(__file__).parent
DSN = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")

TSQ_AND = (
    "websearch_to_tsquery('french', %(q)s) || websearch_to_tsquery('german', %(q)s)"
    " || websearch_to_tsquery('english', %(q)s)"
)
# OR variant: every '&' becomes '|', unless the query carries a negation
TSQ_OR = (
    f"CASE WHEN strpos(({TSQ_AND})::text, '!') > 0"
    f" THEN {TSQ_AND}"
    f" ELSE replace(({TSQ_AND})::text, '&', '|')::tsquery END"
)

SQL = """
WITH query AS (SELECT {tsq} AS tsq),
vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE d.status = 'ready'
  ORDER BY c.embedding <=> %(qvec)s::vector LIMIT %(n)s
),
fts AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, query
  WHERE d.status = 'ready' AND c.tsv @@ query.tsq
  ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC LIMIT %(n)s
)
SELECT d.filename, coalesce(c.section,''), left(c.content, 400)
FROM vec FULL OUTER JOIN fts USING (id)
JOIN chunks c ON c.id = coalesce(vec.id, fts.id)
JOIN documents d ON d.id = c.document_id
ORDER BY coalesce(%(wv)s / (%(rrf_k)s + vec.rnk), 0)
       + coalesce(%(wf)s / (%(rrf_k)s + fts.rnk), 0) DESC
LIMIT %(k)s
"""

# three legs: vector + strict AND (precision) + OR (recall net)
SQL3 = """
WITH qa AS (SELECT {tsq_and} AS tsq),
qo AS (SELECT {tsq_or} AS tsq),
vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE d.status = 'ready'
  ORDER BY c.embedding <=> %(qvec)s::vector LIMIT %(n)s
),
fa AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, qa.tsq) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, qa
  WHERE d.status = 'ready' AND c.tsv @@ qa.tsq
  ORDER BY ts_rank_cd(c.tsv, qa.tsq) DESC LIMIT %(n)s
),
fo AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, qo.tsq) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, qo
  WHERE d.status = 'ready' AND c.tsv @@ qo.tsq
  ORDER BY ts_rank_cd(c.tsv, qo.tsq) DESC LIMIT %(n)s
)
SELECT d.filename, coalesce(c.section,''), left(c.content, 400)
FROM vec FULL OUTER JOIN fa USING (id) FULL OUTER JOIN fo USING (id)
JOIN chunks c ON c.id = coalesce(vec.id, fa.id, fo.id)
JOIN documents d ON d.id = c.document_id
ORDER BY coalesce(1.0 / (%(rrf_k)s + vec.rnk), 0)
       + coalesce(%(wa)s / (%(rrf_k)s + fa.rnk), 0)
       + coalesce(%(wo)s / (%(rrf_k)s + fo.rnk), 0) DESC
LIMIT %(k)s
"""

VARIANTS = [
    ("AND wf=1.0 (baseline)", TSQ_AND, 1.0),
    ("OR  wf=1.0 (naive)", TSQ_OR, 1.0),
    ("OR  wf=0.5", TSQ_OR, 0.5),
    ("OR  wf=0.3", TSQ_OR, 0.3),
    ("OR  wf=0.2", TSQ_OR, 0.2),
    ("OR  wf=0.1", TSQ_OR, 0.1),
    ("OR  wf=0.05", TSQ_OR, 0.05),
]


def rank_of(rows, expect, hint):
    for r, (fn, sec, content) in enumerate(rows, 1):
        if expect.lower() in fn.lower() and (
            not hint or hint.lower() in (sec + " " + content).lower()
        ):
            return r
    for r, (fn, _, _) in enumerate(rows, 1):
        if expect.lower() in fn.lower():
            return r
    return None


def main():
    ap = argparse.ArgumentParser(description="fusion variant sweep (direct SQL)")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    args = ap.parse_args()
    cases = [c for c in json.loads(args.golden.read_text()) if c.get("expect")]
    qembs = load_qembs([c["q"] for c in cases])

    conn = psycopg.connect(DSN)
    print(f"{'variant':<24} {'hit@1':>6} {'hit@3':>6} {'hit@8':>6} {'MRR':>7}   misses")
    for label, tsq, wf in VARIANTS:
        rr = 0.0
        h1 = h3 = h8 = 0
        miss = []
        for c in cases:
            rows = conn.execute(
                SQL.format(tsq=tsq),
                {
                    "q": c["q"],
                    "qvec": as_pgvector(qembs[c["q"]]),
                    "n": 40,
                    "rrf_k": 60,
                    "k": 8,
                    "wv": 1.0,
                    "wf": wf,
                },
            ).fetchall()
            r = rank_of(rows, c["expect"], c.get("hint", ""))
            if r:
                rr += 1 / r
                h1 += r <= 1
                h3 += r <= 3
                h8 += r <= 8
            else:
                miss.append(c["q"][:34])
        n = len(cases)
        more = " +" + str(len(miss) - 2) if len(miss) > 2 else ""
        print(
            f"{label:<24} {h1:>4}/{n:<3} {h3:>4}/{n:<3} {h8:>4}/{n:<3} {rr / n:>7.3f}   "
            f"{'; '.join(miss[:2])}{more}"
        )

    print()
    print(
        f"{'3 legs (wa=AND, wo=OR)':<24} {'hit@1':>6} {'hit@3':>6} {'hit@8':>6} {'MRR':>7}   misses"
    )
    for wa, wo in [(1.0, 0.3), (1.0, 0.15), (1.0, 0.1), (1.0, 0.05), (0.5, 0.1)]:
        rr = 0.0
        h1 = h3 = h8 = 0
        miss = []
        for c in cases:
            rows = conn.execute(
                SQL3.format(tsq_and=TSQ_AND, tsq_or=TSQ_OR),
                {
                    "q": c["q"],
                    "qvec": as_pgvector(qembs[c["q"]]),
                    "n": 40,
                    "rrf_k": 60,
                    "k": 8,
                    "wa": wa,
                    "wo": wo,
                },
            ).fetchall()
            r = rank_of(rows, c["expect"], c.get("hint", ""))
            if r:
                rr += 1 / r
                h1 += r <= 1
                h3 += r <= 3
                h8 += r <= 8
            else:
                miss.append(c["q"][:34])
        n = len(cases)
        more = " +" + str(len(miss) - 2) if len(miss) > 2 else ""
        print(
            f"wa={wa} wo={wo:<14} {h1:>4}/{n:<3} {h3:>4}/{n:<3} {h8:>4}/{n:<3} {rr / n:>7.3f}   "
            f"{'; '.join(miss[:2])}{more}"
        )
    conn.close()


if __name__ == "__main__":
    main()
