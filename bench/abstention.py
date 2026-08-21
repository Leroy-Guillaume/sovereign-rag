"""S6: questions with no answer in the corpus must produce a refusal, not an invention.

The refusal detector is a trilingual regex over the generated answer. It is a
floor, not a verdict: a response it does not match is printed in full-enough
form for manual review (several recorded "ANSWERED" lines turned out to be
refusals phrased outside the pattern; see results/).

Environment:
  SOVEREIGN_RAG_URL      target stack (default http://localhost:8000)
  SOVEREIGN_RAG_API_KEY  bearer key (default sk-demo-admin)

Usage: uv run bench/abstention.py [--golden PATH]
"""

import argparse
import json
import os
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).parent
BASE_URL = os.environ.get("SOVEREIGN_RAG_URL", "http://localhost:8000")
API_KEY = os.environ.get("SOVEREIGN_RAG_API_KEY", "sk-demo-admin")

REFUSAL = re.compile(
    r"aucune information|ne contiennent pas|ne contient pas|ne fournissent pas|pas d'information"
    r"|n'est pas mentionn|ne mentionnent pas|ne fait r[ée]f[ée]rence|pas de mention"
    r"|ne sp[ée]cifient pas|ne traitent pas"
    r"|not contain|no information|do not provide|cannot find|does not (mention|specify|address)"
    r"|do not (mention|specify|address)"
    r"|keine informationen|enthalten keine|nicht enthalten|liegen keine|behandeln keine"
    r"|nicht erw[äa]hnt|keine angaben",
    re.I,
)


def ask(q):
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
            json.dumps({"message": q}),
            "--max-time",
            "180",
        ],
        capture_output=True,
        text=True,
    ).stdout
    deltas = re.findall(r"^event: delta\ndata: (.*)$", out, re.M)
    return "".join(json.loads(d).get("text", "") for d in deltas if d.startswith("{"))


def main():
    ap = argparse.ArgumentParser(description="no-answer (S6) abstention scorer")
    ap.add_argument("--golden", type=pathlib.Path, default=HERE / "golden_v3.json")
    args = ap.parse_args()

    cases = [c for c in json.loads(args.golden.read_text()) if c["stratum"] == "S6"]
    ok = 0
    print(f"{len(cases)} questions with no answer in the corpus\n")
    for c in cases:
        text = ask(c["q"])
        abstained = bool(REFUSAL.search(text))
        ok += abstained
        print(f"  {'ABSTAINED' if abstained else 'ANSWERED ':<9} {c['q'][:64]}")
        if not abstained:
            print(f"            -> {text[:130]}")
    print(f"\n  abstention rate : {ok}/{len(cases)} (regex floor; review ANSWERED lines by hand)")


if __name__ == "__main__":
    main()
