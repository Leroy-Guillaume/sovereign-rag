"""Measure hit@k / MRR / lexical contribution over a golden set, through the live API.

Queries go through the /api/chat SSE endpoint exactly like the frontend, so
the whole retrieval pipeline is measured: hybrid RRF fusion plus reranking.
Rows with an empty "expect" (stratum S6) measure abstention, not rank; they
are skipped here and scored by abstention.py instead.

Environment:
  SOVEREIGN_RAG_URL      target stack (default http://localhost:8000)
  SOVEREIGN_RAG_API_KEY  bearer key (default sk-demo-admin)

Usage: uv run bench/run.py [label] [--golden PATH] [--limit N]
           [--min-hit8 F] [--min-mrr F]

With --min-hit8 / --min-mrr the process exits nonzero when the measured
hit@8 ratio or MRR falls below the floor: that is the CI smoke gate.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import time

from _tracking import track

HERE = pathlib.Path(__file__).parent
BASE_URL = os.environ.get("SOVEREIGN_RAG_URL", "http://localhost:8000")
API_KEY = os.environ.get("SOVEREIGN_RAG_API_KEY", "sk-demo-admin")


MODE = "standard"


def search(q):
    out = subprocess.run(
        [
            "curl",
            "-s",
            "-N",
            "-X",
            "POST",
            f"{BASE_URL}/api/chat",
            "-H",
            f"Authorization: Bearer {API_KEY}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"message": q, "mode": MODE}),
            "--max-time",
            "180",
        ],
        capture_output=True,
        text=True,
    ).stdout
    m = re.findall(r"^event: sources\ndata: (.*)$", out, re.M)
    return json.loads(m[0]) if m else []


def rank_of(hits, expect, hint):
    for r, h in enumerate(hits, 1):
        fn = h.get("filename") or ""
        if expect.lower() in fn.lower():
            blob = (h.get("section") or "") + " " + (h.get("content") or h.get("excerpt") or "")
            if not hint or hint.lower() in blob.lower():
                return r
    for r, h in enumerate(hits, 1):  # fallback: the right document is enough
        if expect.lower() in (h.get("filename") or "").lower():
            return r
    return None


def main():
    ap = argparse.ArgumentParser(description="hit@k / MRR runner")
    ap.add_argument("label", nargs="?", default="run")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    ap.add_argument("--limit", type=int, default=0, help="score only the first N questions")
    ap.add_argument("--min-hit8", type=float, default=0.0, help="fail below this hit@8 ratio")
    ap.add_argument("--min-mrr", type=float, default=0.0, help="fail below this MRR")
    ap.add_argument("--mode", choices=["standard", "deep"], default="standard")
    ap.add_argument("--stratum", default="", help="comma list, e.g. S5,S2 (default: all)")
    args = ap.parse_args()
    global MODE
    MODE = args.mode

    cases = [c for c in json.loads(args.golden.read_text()) if c.get("expect")]
    if args.stratum:
        wanted = set(args.stratum.split(","))
        cases = [c for c in cases if c.get("stratum") in wanted]
    if args.limit > 0:
        cases = cases[: args.limit]

    rr = 0.0
    h1 = h3 = h5 = h8 = 0
    fts = 0
    tot = 0
    miss = []
    t0 = time.time()
    for c in cases:
        hits = search(c["q"])
        tot += len(hits)
        fts += sum(1 for h in hits if h.get("fts_rank") is not None)
        r = rank_of(hits, c["expect"], c.get("hint", ""))
        if r:
            rr += 1 / r
            h1 += r <= 1
            h3 += r <= 3
            h5 += r <= 5
            h8 += r <= 8
        else:
            miss.append(c["q"][:62])
    n = len(cases)
    elapsed = time.time() - t0
    print(f"===== {args.label} =====")
    print(f"  questions : {n}")
    print(f"  hit@1  : {h1}/{n}  ({100 * h1 / n:.0f} %)")
    print(f"  hit@3  : {h3}/{n}  ({100 * h3 / n:.0f} %)")
    print(f"  hit@5  : {h5}/{n}  ({100 * h5 / n:.0f} %)")
    print(f"  hit@8  : {h8}/{n}  ({100 * h8 / n:.0f} %)")
    print(f"  MRR    : {rr / n:.3f}")
    print(f"  lexical contribution : {fts}/{tot} sources ({100 * fts / tot if tot else 0:.0f} %)")
    print(f"  elapsed : {elapsed:.0f} s")
    if miss:
        print(f"  MISSES ({len(miss)}):")
        for m in miss:
            print(f"    - {m}")
    mrr = rr / n
    track(
        "retrieval",
        args.label,
        params={
            "golden": args.golden.name,
            "limit": args.limit,
            "min_hit8": args.min_hit8,
            "min_mrr": args.min_mrr,
            "base_url": BASE_URL,
        },
        metrics={
            "hit_at_1": h1 / n,
            "hit_at_3": h3 / n,
            "hit_at_5": h5 / n,
            "hit_at_8": h8 / n,
            "mrr": mrr,
            "lexical_contribution": fts / tot if tot else 0.0,
            "questions": n,
            "elapsed_s": elapsed,
        },
    )
    if h8 / n < args.min_hit8 or mrr < args.min_mrr:
        print(
            f"GATE FAILED: hit@8 {h8}/{n} (floor {args.min_hit8:.2f}), "
            f"MRR {mrr:.3f} (floor {args.min_mrr:.2f})"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
