# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
# LangGraph's StateGraph generics do not resolve under strict mode; the
# waivers above are scoped to this file, everything else stays strict.
"""The deep-search graph: plan, search, write, verify, with routed repair.

LangGraph runs the routing and the bounded cycles; every model call goes
through the project's LLMClient (PII boundary included) and every search
through the project's VectorStore with the caller's ACL. Node outputs are
constrained JSON rather than native tool calls: deterministic to parse,
and measured as reliable on the local model by bench/agents/.
"""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

import structlog
from langgraph.graph import END, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from ..auth import User
from ..config import Settings
from ..embeddings.base import EmbeddingClient
from ..llm.base import ChatMessage, LLMClient, collect
from ..reranking.base import Reranker
from ..store.base import SearchHit, VectorStore
from .state import (
    MAX_REPLANS,
    MAX_SEARCH_REPAIRS,
    MAX_WRITE_REPAIRS,
    Claim,
    DeepState,
)

logger = structlog.get_logger()

EmitStep = Callable[[str, str], Awaitable[None]]

_PLAN_PROMPT = """\
Split the user's question into the smallest set of focused sub-questions
(1 to 4), each answerable by one search over a legal corpus. Keep the
question's language. Answer with a JSON array of strings only."""

_WRITE_PROMPT = """\
You are a careful documentation assistant. Answer the question using ONLY
the numbered context passages below. Cite every passage you rely on with
its bracketed number, e.g. [1] or [2][3]. Answer in the language of the
question. If the context does not contain the answer for a part, say so
explicitly; never invent facts."""

_VERIFY_PROMPT = """\
You are a strict fact checker. For EVERY factual claim in the draft, check
it against the numbered passages. Answer with a JSON array of objects:
{"text": "<the claim>", "verdict": "supported" | "misattributed" |
"unsupported" | "unanswerable", "fix_query": "<a focused search query when
verdict is unsupported, else empty>"}.
"misattributed" means the evidence exists in the passages but the cited
number is wrong. "unanswerable" means the passages cannot cover this claim
at all. Judge ONLY against the passages. JSON only."""


def _json_payload(text: str) -> Any:
    """Extract the first JSON array/object from a model reply, tolerantly."""
    match = re.search(r"\[.*\]|\{.*\}", text, re.S)
    if match is None:
        raise ValueError("no JSON in model output")
    return json.loads(match.group(0))


def _blocks(evidence: list[SearchHit]) -> str:
    parts = []
    for index, hit in enumerate(evidence, start=1):
        location = hit.filename + (f" - {hit.section}" if hit.section else "")
        parts.append(f"[{index}] {location}:\n{hit.content}")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class DeepDeps:
    llm: LLMClient
    embedder: EmbeddingClient
    store: VectorStore
    reranker: Reranker | None
    settings: Settings
    user: User
    emit: EmitStep


def build_deep_graph(deps: DeepDeps) -> Any:
    async def ask(system: str, user_content: str) -> str:
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user_content),
        ]
        text, _, _ = await collect(deps.llm.stream_chat(messages))
        return text

    async def plan(state: DeepState) -> dict[str, Any]:
        try:
            raw = _json_payload(await ask(_PLAN_PROMPT, state["question"]))
            subqs = [str(q) for q in raw if str(q).strip()][:4] or [state["question"]]
        except (ValueError, json.JSONDecodeError):
            subqs = [state["question"]]
        await deps.emit("planner", f"{len(subqs)} sub-questions")
        return {"plan": subqs, "pending_queries": list(subqs)}

    async def search(state: DeepState) -> dict[str, Any]:
        pool: dict[str, SearchHit] = {str(h.chunk_id): h for h in state["evidence"]}
        queries = state["pending_queries"]
        for query in queries:
            embedding = await deps.embedder.embed_query(query)
            hits = await deps.store.hybrid_search(query, embedding, user_id=deps.user.id, k=12)
            for hit in hits:
                pool.setdefault(str(hit.chunk_id), hit)
        merged = list(pool.values())
        if deps.reranker is not None and merged:
            merged = await deps.reranker.rerank(state["question"], merged, k=10)
        else:
            merged = merged[:10]
        await deps.emit("searcher", f"{len(queries)} queries, {len(merged)} passages")
        return {"evidence": merged, "pending_queries": []}

    async def write(state: DeepState) -> dict[str, Any]:
        content = (
            f"{_WRITE_PROMPT}\n\nContext:\n\n{_blocks(state['evidence'])}"
            if state["evidence"]
            else _WRITE_PROMPT
        )
        draft = await ask(content, state["question"])
        await deps.emit("writer", f"{len(draft)} chars")
        return {"draft": draft}

    async def verify(state: DeepState) -> dict[str, Any]:
        prompt = f"Draft:\n{state['draft']}\n\nPassages:\n\n{_blocks(state['evidence'])}"
        claims: list[Claim] = []
        try:
            raw = _json_payload(await ask(_VERIFY_PROMPT, prompt))
            for item in raw:
                if not isinstance(item, dict):
                    continue
                verdict = item.get("verdict", "supported")
                if verdict not in ("supported", "misattributed", "unsupported", "unanswerable"):
                    verdict = "supported"
                claims.append(
                    Claim(
                        text=str(item.get("text", ""))[:200],
                        verdict=cast("Any", verdict),
                        fix_query=str(item.get("fix_query", ""))[:200],
                    )
                )
        except (ValueError, json.JSONDecodeError):
            logger.warning("deep_verifier_unparseable")
        bad = [c for c in claims if c["verdict"] != "supported"]
        await deps.emit("verifier", f"{len(claims)} claims, {len(bad)} flagged")
        return {"claims": claims}

    def route(state: DeepState) -> Literal["write", "search", "plan", "abstain", "deliver"]:
        claims = state["claims"]
        if not claims:
            return "deliver"
        verdicts = {c["verdict"] for c in claims}
        # Whole answer out of corpus reach: the honest exit.
        if verdicts == {"unanswerable"}:
            return "abstain"
        if "unsupported" in verdicts and state["search_repairs"] < MAX_SEARCH_REPAIRS:
            return "search"
        if "misattributed" in verdicts and state["write_repairs"] < MAX_WRITE_REPAIRS:
            return "write"
        # Everything supported, or repair budgets exhausted: ship what holds.
        if verdicts <= {"supported", "unanswerable"} or (
            state["search_repairs"] >= MAX_SEARCH_REPAIRS
            and state["write_repairs"] >= MAX_WRITE_REPAIRS
        ):
            return "deliver"
        if state["replans"] < MAX_REPLANS:
            return "plan"
        return "deliver"

    async def before_search_repair(state: DeepState) -> dict[str, Any]:
        fixes = [c["fix_query"] for c in state["claims"] if c["verdict"] == "unsupported"]
        return {
            "pending_queries": [f for f in fixes if f] or [state["question"]],
            "search_repairs": state["search_repairs"] + 1,
            "claims": [],
        }

    async def before_write_repair(state: DeepState) -> dict[str, Any]:
        return {"write_repairs": state["write_repairs"] + 1, "claims": []}

    async def before_replan(state: DeepState) -> dict[str, Any]:
        return {"replans": state["replans"] + 1, "claims": [], "evidence": []}

    async def deliver(state: DeepState) -> dict[str, Any]:
        return {"outcome": "delivered"}

    async def abstain(state: DeepState) -> dict[str, Any]:
        await deps.emit("verifier", "corpus cannot answer, abstaining")
        return {"outcome": "abstained", "evidence": [], "draft": ""}

    graph = StateGraph(DeepState)
    graph.add_node("plan", plan)
    graph.add_node("search", search)
    graph.add_node("write", write)
    graph.add_node("verify", verify)
    graph.add_node("search_repair", before_search_repair)
    graph.add_node("write_repair", before_write_repair)
    graph.add_node("replan", before_replan)
    graph.add_node("deliver", deliver)
    graph.add_node("abstain", abstain)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "search")
    graph.add_edge("search", "write")
    graph.add_edge("write", "verify")
    graph.add_conditional_edges(
        "verify",
        route,
        {
            "search": "search_repair",
            "write": "write_repair",
            "plan": "replan",
            "deliver": "deliver",
            "abstain": "abstain",
        },
    )
    graph.add_edge("search_repair", "search")
    graph.add_edge("write_repair", "write")
    graph.add_edge("replan", "plan")
    graph.add_edge("deliver", END)
    graph.add_edge("abstain", END)
    return graph.compile()


def initial_state(question: str) -> DeepState:
    return DeepState(
        question=question,
        plan=[],
        evidence=[],
        pending_queries=[],
        draft="",
        claims=[],
        search_repairs=0,
        write_repairs=0,
        replans=0,
        outcome="",
    )
