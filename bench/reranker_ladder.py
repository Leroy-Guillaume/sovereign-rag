"""Reranker ladder: the same 40-candidate pools scored by each candidate model.

Quality comparison only: pools are extracted once from the shipped fusion
SQL, then every model reranks the identical pools, so differences are the
reranker and nothing else. Latency numbers here reflect whatever device the
library picks (set BENCH_EMBED_DEVICE / device below for control); the
production CPU latency of the retained candidate is measured separately by
rerank_eval.py.

Needs direct database access, the backend package importable, and a local
embedding model matching the stack's EMBEDDING_MODEL (see qembed.py).

Environment:
  DATABASE_URL  Postgres DSN (default postgresql://rag:rag@localhost:5432/rag)
  BENCH_DEVICE  torch device for the rerankers (default: library auto-detection)

Usage: cd backend && uv run --extra local ../bench/reranker_ladder.py [--golden PATH]
"""

import argparse
import json
import os
import pathlib
import time
import warnings

import psycopg
from qembed import as_pgvector, load_qembs

from sovereign_rag.store.pgvector import HYBRID_SEARCH_TEMPLATE, MAX_DF_RATIO, QUERY_STOPLIST

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).parent
DSN = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")
DEVICE = os.environ.get("BENCH_DEVICE") or None

SQL = HYBRID_SEARCH_TEMPLATE.format(acl="").replace(
    "SELECT id, document_id, filename, section, page, content, vec_rank, fts_rank, score",
    "SELECT filename, coalesce(section,''), content",
)

MODELS = [
    ("mmarco-MiniLM (118M)", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", {}),
    (
        "gte-multilingual (306M)",
        "Alibaba-NLP/gte-multilingual-reranker-base",
        {"trust_remote_code": True},
    ),
    ("bge-reranker-v2-m3 (568M)", "BAAI/bge-reranker-v2-m3", {}),
]


def rank_of(rows, expect, hint):
    for r, row in enumerate(rows, 1):
        if expect.lower() in row[0].lower() and (
            not hint or hint.lower() in (row[1] + " " + row[2]).lower()
        ):
            return r
    for r, row in enumerate(rows, 1):
        if expect.lower() in row[0].lower():
            return r
    return None


def evaluate(cases, pools, ce):
    per = {}
    for c in cases:
        rows = pools[c["q"]]
        scores = ce.predict([(c["q"], row[2]) for row in rows])
        pairs = sorted(zip(scores, rows, strict=True), key=lambda x: -float(x[0]))
        ranked = [row for _, row in pairs][:8]
        r = rank_of(ranked, c["expect"], c.get("hint", ""))
        st = per.setdefault(c["stratum"], {"n": 0, "h1": 0, "h3": 0, "h8": 0, "rr": 0.0})
        st["n"] += 1
        if r:
            st["rr"] += 1 / r
            st["h1"] += r <= 1
            st["h3"] += r <= 3
            st["h8"] += r <= 8
    return per


def main():
    ap = argparse.ArgumentParser(description="reranker quality ladder over shared pools")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    args = ap.parse_args()
    cases = [c for c in json.loads(args.golden.read_text()) if c.get("expect")]
    qembs = load_qembs([c["q"] for c in cases])

    print("extracting the 40-candidate pools...", flush=True)
    conn = psycopg.connect(DSN)
    pools = {}
    for c in cases:
        pools[c["q"]] = conn.execute(
            SQL,
            {
                "q": c["q"],
                "qvec": as_pgvector(qembs[c["q"]]),
                "n": 40,
                "rrf_k": 60,
                "w_fts": 1.0,
                "doc_cap": 3,
                "stoplist": QUERY_STOPLIST,
                "max_df": MAX_DF_RATIO,
                "k": 40,
            },
        ).fetchall()
    conn.close()
    print(f"{len(pools)} pools ready", flush=True)

    from sentence_transformers.cross_encoder import CrossEncoder

    print(
        f"\n{'model':<30} {'hit@1':>7} {'hit@3':>7} {'hit@8':>7} {'MRR':>6}   S2/S5 (the targets)"
    )
    for label, model_id, kwargs in MODELS:
        try:
            ce = CrossEncoder(
                model_id,
                device=DEVICE,
                automodel_args=kwargs,
                trust_remote_code=kwargs.get("trust_remote_code", False),
            )
            ce.predict([("warmup", "warmup")])
            t0 = time.time()
            per = evaluate(cases, pools, ce)
            dur = time.time() - t0
            n = sum(s["n"] for s in per.values())
            h1 = sum(s["h1"] for s in per.values())
            h3 = sum(s["h3"] for s in per.values())
            h8 = sum(s["h8"] for s in per.values())
            rr = sum(s["rr"] for s in per.values())
            s2 = per.get("S2", {"rr": 0, "n": 1})
            s5 = per.get("S5", {"rr": 0, "n": 1})
            print(
                f"{label:<30} {h1:>4}/{n} {h3:>4}/{n} {h8:>4}/{n} {rr / n:>6.3f}   "
                f"S2={s2['rr'] / s2['n']:.2f} S5={s5['rr'] / s5['n']:.2f}  ({dur:.0f}s)",
                flush=True,
            )
            del ce
        except Exception as e:
            print(f"{label:<30} FAILED: {type(e).__name__}: {str(e)[:90]}", flush=True)


if __name__ == "__main__":
    main()
