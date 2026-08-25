"""Probe a local model's multi-turn tool-calling before wiring it as the
deep-search orchestrator brain.

Scenario per question: the model gets a `search` tool and a two-axis legal
question. A capable orchestrator model must (1) call search with sensible
arguments, (2) call it AGAIN for the second axis after seeing the first
results, (3) then stop calling and answer citing both. Scored mechanically;
the fake search returns canned passages so the probe is deterministic and
needs no running stack.

Usage: uv run bench/agents/toolcall_probe.py --model qwen3:14b
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from _tracking import track

OLLAMA = "http://localhost:11434/api/chat"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the legal corpus. Returns the most relevant passages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "the search query"},
                    "lang": {
                        "type": "string",
                        "enum": ["fr", "de", "en"],
                        "description": "query language",
                    },
                },
                "required": ["query"],
            },
        },
    }
]

# Two-axis questions: answering both halves needs two DIFFERENT searches.
QUESTIONS = [
    (
        "Quelles sont les obligations de securite selon la nLPD, et quels sont "
        "les delais d'annonce d'une violation au PFPDT ?",
        ["securite", "annonce|violation|delai"],
    ),
    (
        "Was verlangt das DSG bei der Auftragsbearbeitung, und welche Rechte "
        "hat die betroffene Person auf Auskunft?",
        ["auftrag", "auskunft"],
    ),
    (
        "Under NIS2, which entities are in scope, and what are the incident reporting deadlines?",
        ["scope|entit", "incident|report|deadline"],
    ),
    (
        "Que dit le RGPD sur le consentement, et quelles sanctions le texte "
        "prevoit-il en cas de non-respect ?",
        ["consentement", "sanction|amende"],
    ),
]

CANNED = (
    "[1] corpus.md - Art. 8: Le responsable du traitement doit assurer une "
    "securite adaptee au risque par des mesures appropriees."
)


NO_THINK = False


def call(model: str, messages: list[dict], with_tools: bool) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    if NO_THINK:
        body["think"] = False
    if with_tools:
        body["tools"] = TOOLS
    req = urllib.request.Request(
        OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]


def run_scenario(model: str, question: str, axes: list[str]) -> dict:
    import re

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are a research orchestrator. Use the search tool to gather "
                "evidence for EVERY distinct aspect of the question (one focused "
                "search per aspect, in the question's language), then answer "
                "citing the passages. Never answer from memory."
            ),
        },
        {"role": "user", "content": question},
    ]
    queries: list[str] = []
    t0 = time.time()
    for _turn in range(6):
        message = call(model, messages, with_tools=True)
        calls = message.get("tool_calls") or []
        messages.append(message)
        if not calls:
            break
        for tool_call in calls:
            arguments = tool_call["function"].get("arguments") or {}
            queries.append(str(arguments.get("query", "")))
            messages.append({"role": "tool", "content": CANNED})
    answered = bool((messages[-1].get("content") or "").strip()) and not (
        messages[-1].get("tool_calls")
    )
    covered = sum(1 for axis in axes if any(re.search(axis, q, re.I) for q in queries))
    return {
        "calls": len(queries),
        "multi": len(queries) >= 2,
        "axes_covered": covered,
        "axes_total": len(axes),
        "answered": answered,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--no-think", action="store_true", help="disable qwen3 thinking")
    args = ap.parse_args()
    global NO_THINK  # probe-level switch, set once
    NO_THINK = args.no_think
    results = []
    for question, axes in QUESTIONS:
        outcome = run_scenario(args.model, question, axes)
        results.append(outcome)
        print(f"  {outcome} | {question[:60]}")
    ok = sum(
        1 for r in results if r["multi"] and r["answered"] and r["axes_covered"] == r["axes_total"]
    )
    calls = sum(r["calls"] for r in results)
    secs = sum(r["seconds"] for r in results)
    print(f"===== {args.model} =====")
    print(f"  full orchestration: {ok}/{len(results)} | tool calls: {calls} | total: {secs:.0f} s")
    track(
        "toolcalling",
        args.model + ("-nothink" if args.no_think else ""),
        params={"model": args.model, "no_think": args.no_think},
        metrics={
            "full_orchestration_ratio": ok / len(results),
            "tool_calls": calls,
            "total_s": secs,
        },
    )


if __name__ == "__main__":
    main()
