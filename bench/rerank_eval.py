"""With / without reranker: fusion (pool 40) -> cross-encoder -> top 8, per stratum.

The control arm serves the fused order directly at k=8; the treatment arm
reranks a 40-candidate pool with the ONNX cross-encoder on CPU, which is the
production execution path, so the reported latency is the real cost.

Needs direct database access, the backend package importable, and a local
embedding model matching the stack's EMBEDDING_MODEL (see qembed.py).

Environment:
  DATABASE_URL  Postgres DSN (default postgresql://rag:rag@localhost:5432/rag)

Usage: cd backend && uv run --extra local ../bench/rerank_eval.py [--golden PATH]
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

SQL = HYBRID_SEARCH_TEMPLATE.format(acl="").replace(
    "SELECT id, document_id, filename, section, page, content, vec_rank, fts_rank, score",
    "SELECT filename, coalesce(section,''), content, vec_rank AS vr, fts_rank AS fr",
)


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


def evaluate(cases, qembs, ce, rerank):
    conn = psycopg.connect(DSN)
    per = {}
    lat = []
    for c in cases:
        pool_k = 40 if rerank else 8
        rows = conn.execute(
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
                "k": pool_k,
            },
        ).fetchall()
        if rerank and rows:
            t0 = time.time()
            scores = ce.predict([(c["q"], row[2]) for row in rows])
            lat.append((time.time() - t0) * 1000)
            pairs = sorted(zip(scores, rows, strict=True), key=lambda x: -x[0])
            rows = [row for _, row in pairs][:8]
        r = rank_of(rows, c["expect"], c.get("hint", ""))
        st = per.setdefault(c["stratum"], {"n": 0, "h1": 0, "h3": 0, "h8": 0, "rr": 0.0})
        st["n"] += 1
        if r:
            st["rr"] += 1 / r
            st["h1"] += r <= 1
            st["h3"] += r <= 3
            st["h8"] += r <= 8
    conn.close()
    return per, lat


def report(label, per, lat):
    n = sum(s["n"] for s in per.values())
    h1 = sum(s["h1"] for s in per.values())
    h3 = sum(s["h3"] for s in per.values())
    h8 = sum(s["h8"] for s in per.values())
    rr = sum(s["rr"] for s in per.values())
    extra = ""
    if lat:
        extra = f"  rerank latency p50={sorted(lat)[len(lat) // 2]:.0f}ms max={max(lat):.0f}ms"
    print(f"===== {label} =====")
    print(
        f"  hit@1={h1}/{n} ({100 * h1 / n:.0f}%)  hit@3={h3}/{n} ({100 * h3 / n:.0f}%)  "
        f"hit@8={h8}/{n} ({100 * h8 / n:.0f}%)  MRR={rr / n:.3f}{extra}"
    )
    for stratum in sorted(per):
        s = per[stratum]
        print(
            f"  {stratum}: n={s['n']:<3} hit@1={s['h1']:<3} hit@3={s['h3']:<3} "
            f"hit@8={s['h8']:<3} MRR={s['rr'] / s['n']:.3f}"
        )
    return h1, h3, h8, rr / n


def main():
    ap = argparse.ArgumentParser(description="reranker on/off comparison")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    args = ap.parse_args()
    cases = [c for c in json.loads(args.golden.read_text()) if c.get("expect")]
    qembs = load_qembs([c["q"] for c in cases])

    from sentence_transformers.cross_encoder import CrossEncoder

    ce = CrossEncoder(
        "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        backend="onnx",
        model_kwargs={"provider": "CPUExecutionProvider", "file_name": "onnx/model_O3.onnx"},
    )
    ce.predict([("warmup", "warmup")])

    base = report("WITHOUT reranker (control)", *evaluate(cases, qembs, ce, rerank=False))
    rr = report("WITH reranker (pool 40 -> top 8)", *evaluate(cases, qembs, ce, rerank=True))
    print(
        f"\n  DELTA : hit@1 {rr[0] - base[0]:+d}  hit@3 {rr[1] - base[1]:+d}  "
        f"hit@8 {rr[2] - base[2]:+d}  MRR {rr[3] - base[3]:+.3f}"
    )


if __name__ == "__main__":
    main()
