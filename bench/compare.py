"""Old vs current fusion algorithm, per stratum, in direct SQL (no LLM generation).

The old arm is the naive two-leg fusion kept inline below; the current arm is
imported from the backend so this comparison always tracks what actually
ships (ACL predicate removed: the bench measures retrieval over the whole
corpus). Ends with the lexical-weight and rrf_k calibration sweeps that set
the shipped defaults.

Needs direct database access, the backend package importable, and a local
embedding model matching the stack's EMBEDDING_MODEL (see qembed.py).

Environment:
  DATABASE_URL  Postgres DSN (default postgresql://rag:rag@localhost:5432/rag)

Usage: cd backend && uv run --extra local ../bench/compare.py [--golden PATH]
"""

import argparse
import json
import os
import pathlib

import psycopg
from qembed import as_pgvector, load_qembs

from sovereign_rag.store.pgvector import HYBRID_SEARCH_TEMPLATE, MAX_DF_RATIO, QUERY_STOPLIST

HERE = pathlib.Path(__file__).parent
DSN = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")

OLD_SQL = """
WITH query AS (
  SELECT websearch_to_tsquery('french', %(q)s) || websearch_to_tsquery('german', %(q)s)
      || websearch_to_tsquery('english', %(q)s) AS tsq
), vec AS (
  SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.status='ready'
  ORDER BY c.embedding <=> %(qvec)s::vector LIMIT %(n)s
), fts AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC) AS rnk
  FROM chunks c JOIN documents d ON d.id = c.document_id, query
  WHERE d.status='ready' AND c.tsv @@ query.tsq
  ORDER BY ts_rank_cd(c.tsv, query.tsq) DESC LIMIT %(n)s
)
SELECT d.filename, coalesce(c.section,''), left(c.content,400),
       vec.rnk AS vr, fts.rnk AS fr
FROM vec FULL OUTER JOIN fts USING (id)
JOIN chunks c ON c.id = coalesce(vec.id, fts.id)
JOIN documents d ON d.id = c.document_id
ORDER BY coalesce(1.0/(60+vec.rnk),0)+coalesce(1.0/(60+fts.rnk),0) DESC LIMIT %(k)s
"""

NEW_SQL = HYBRID_SEARCH_TEMPLATE.format(acl="").replace(
    "SELECT id, document_id, filename, section, page, content, vec_rank, fts_rank, score",
    "SELECT filename, coalesce(section,''), left(content,400), vec_rank AS vr, fts_rank AS fr",
)


def rank_of(rows, expect, hint):
    for r, row in enumerate(rows, 1):
        fn, sec, content = row[0], row[1], row[2]
        if expect.lower() in fn.lower() and (
            not hint or hint.lower() in (sec + " " + content).lower()
        ):
            return r
    for r, row in enumerate(rows, 1):
        if expect.lower() in row[0].lower():
            return r
    return None


def run(conn, cases, qembs, sql, params_extra):
    per = {}
    fts_contrib = 0
    total_rows = 0
    for c in cases:
        params = {
            "q": c["q"],
            "qvec": as_pgvector(qembs[c["q"]]),
            "n": 40,
            "rrf_k": 60,
            "k": 8,
            **params_extra,
        }
        rows = conn.execute(sql, params).fetchall()
        total_rows += len(rows)
        fts_contrib += sum(1 for row in rows if row[4] is not None)
        r = rank_of(rows, c["expect"], c.get("hint", ""))
        st = per.setdefault(
            c["stratum"], {"n": 0, "h1": 0, "h3": 0, "h8": 0, "rr": 0.0, "miss": []}
        )
        st["n"] += 1
        if r:
            st["rr"] += 1 / r
            st["h1"] += r <= 1
            st["h3"] += r <= 3
            st["h8"] += r <= 8
        else:
            st["miss"].append(c["q"][:46])
    return per, fts_contrib, total_rows


def report(label, per, fts, tot):
    n = sum(s["n"] for s in per.values())
    h1 = sum(s["h1"] for s in per.values())
    h3 = sum(s["h3"] for s in per.values())
    h8 = sum(s["h8"] for s in per.values())
    rr = sum(s["rr"] for s in per.values())
    print(f"\n===== {label} =====")
    print(
        f"  GLOBAL  n={n}  hit@1={h1}/{n} ({100 * h1 / n:.0f}%)  "
        f"hit@3={h3}/{n} ({100 * h3 / n:.0f}%)  hit@8={h8}/{n} ({100 * h8 / n:.0f}%)  "
        f"MRR={rr / n:.3f}"
    )
    print(f"  lexical contribution : {fts}/{tot} ({100 * fts / tot:.0f}%)")
    for stratum in sorted(per):
        s = per[stratum]
        print(
            f"  {stratum}: n={s['n']:<3} hit@1={s['h1']:<3} hit@3={s['h3']:<3} "
            f"hit@8={s['h8']:<3} MRR={s['rr'] / s['n']:.3f}"
        )
    return {"H1": h1, "H3": h3, "H8": h8, "MRR": rr / n, "N": n}


def main():
    ap = argparse.ArgumentParser(description="old vs current fusion, per stratum")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    args = ap.parse_args()
    cases = [c for c in json.loads(args.golden.read_text()) if c.get("expect")]
    qembs = load_qembs([c["q"] for c in cases])
    new_params = {"stoplist": QUERY_STOPLIST, "max_df": MAX_DF_RATIO, "w_fts": 1.0, "doc_cap": 3}

    conn = psycopg.connect(DSN)
    old = report("OLD (naive two-leg RRF)", *run(conn, cases, qembs, OLD_SQL, {}))
    new = report("CURRENT (shipped fusion)", *run(conn, cases, qembs, NEW_SQL, new_params))
    print(
        f"\n  DELTA : hit@1 {new['H1'] - old['H1']:+d}  hit@3 {new['H3'] - old['H3']:+d}  "
        f"hit@8 {new['H8'] - old['H8']:+d}  MRR {new['MRR'] - old['MRR']:+.3f}"
    )

    print("\n--- w_fts calibration (current SQL, doc_cap=3) ---")
    print(f"{'w_fts':<7} {'hit@1':>6} {'hit@3':>6} {'hit@8':>6} {'MRR':>7}")
    for w in [1.0, 0.7, 0.5, 0.4, 0.3]:
        per, _, _ = run(conn, cases, qembs, NEW_SQL, {**new_params, "w_fts": w})
        n = sum(s["n"] for s in per.values())
        h1 = sum(s["h1"] for s in per.values())
        h3 = sum(s["h3"] for s in per.values())
        h8 = sum(s["h8"] for s in per.values())
        rr = sum(s["rr"] for s in per.values())
        print(f"{w:<7} {h1:>4}/{n} {h3:>4}/{n} {h8:>4}/{n} {rr / n:>7.3f}")

    print("\n--- and with rrf_k=20 ---")
    for w in [1.0, 0.5, 0.3]:
        per, _, _ = run(
            conn,
            cases,
            qembs,
            NEW_SQL.replace("%(rrf_k)s", "20"),
            {**new_params, "w_fts": w, "rrf_k": 20},
        )
        n = sum(s["n"] for s in per.values())
        h1 = sum(s["h1"] for s in per.values())
        h3 = sum(s["h3"] for s in per.values())
        h8 = sum(s["h8"] for s in per.values())
        rr = sum(s["rr"] for s in per.values())
        print(f"k=20 w={w:<5} {h1:>4}/{n} {h3:>4}/{n} {h8:>4}/{n} {rr / n:>7.3f}")
    conn.close()


if __name__ == "__main__":
    main()
