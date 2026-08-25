# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
# LangGraph's StateGraph generics do not resolve under strict mode; the
# waivers are scoped to this file, everything else stays strict.
"""The compliance audit graph: map a regulation, hunt evidence, judge, report.

Four agents over the project's own clients (PII boundary and ACL apply
unchanged): the CARTOGRAPHER extracts the regulation's requirements, the
INVESTIGATOR searches the caller's OTHER documents for evidence per
requirement, the EVALUATOR rules compliant / gap / indeterminate with the
evidence cited, the REPORTER writes the executive summary. The durable
checkpoint is one finding per requirement, persisted by the service after
each evaluation: a restarted job resumes at the first unevaluated
requirement instead of re-paying the run.
"""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from ..auth import User
from ..config import Settings
from ..embeddings.base import EmbeddingClient
from ..llm.base import ChatMessage, LLMClient, collect
from ..store.base import VectorStore

logger = structlog.get_logger()

MAX_REQUIREMENTS = 30
EVIDENCE_K = 6

_MAP_PROMPT = """\
Extract the concrete obligations (requirements) from this regulation
excerpt. Each requirement is one enforceable duty. Keep the excerpt's
language. Answer with a JSON array of objects:
{"ref": "<article or section reference>", "text": "<the obligation, one
sentence>"}. JSON only, at most 10 items, skip definitions and preambles."""

_JUDGE_PROMPT = """\
You are a compliance assessor. Decide whether the internal documents below
satisfy the requirement. Answer with ONE JSON object:
{"verdict": "compliant" | "gap" | "indeterminate", "rationale": "<one or
two sentences in the requirement's language>", "evidence": [<indices of
the passages that support your verdict, e.g. 1, 3>]}.
"compliant" needs explicit supporting passages. "gap" means the documents
clearly do not cover the requirement. "indeterminate" when the passages
are related but insufficient to decide. JSON only."""


class Requirement(TypedDict):
    ref: str
    text: str


class Evidence(TypedDict):
    filename: str
    excerpt: str


class Finding(TypedDict):
    ref: str
    verdict: str
    rationale: str
    evidence: list[Evidence]


class AuditState(TypedDict):
    regulation_id: str
    regulation_text: list[str]  # the regulation's chunks, in order
    requirements: list[Requirement]
    findings: list[Finding]
    summary: str


def _json_payload(text: str) -> Any:
    match = re.search(r"\[.*\]|\{.*\}", text, re.S)
    if match is None:
        raise ValueError("no JSON in model output")
    return json.loads(match.group(0))


@dataclass(frozen=True)
class AuditDeps:
    llm: LLMClient
    embedder: EmbeddingClient
    store: VectorStore
    settings: Settings
    user: User
    # Called after the cartographer (with the requirement list) and after
    # EVERY evaluated requirement: the service persists the checkpoint there.
    on_requirements: Callable[[list[Requirement]], Awaitable[None]]
    on_finding: Callable[[Finding], Awaitable[None]]


def build_audit_graph(deps: AuditDeps) -> Any:
    async def ask(system: str, user_content: str) -> str:
        text, _, _ = await collect(
            deps.llm.stream_chat(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user_content),
                ]
            )
        )
        return text

    async def cartographer(state: AuditState) -> dict[str, Any]:
        if state["requirements"]:
            # Resumed job: the map already exists, do not re-extract.
            return {}
        requirements: list[Requirement] = []
        batch: list[str] = []
        size = 0
        batches: list[str] = []
        for chunk in state["regulation_text"]:
            batch.append(chunk)
            size += len(chunk)
            if size > 3000:
                batches.append("\n\n".join(batch))
                batch, size = [], 0
        if batch:
            batches.append("\n\n".join(batch))
        for text in batches:
            if len(requirements) >= MAX_REQUIREMENTS:
                break
            try:
                raw = _json_payload(await ask(_MAP_PROMPT, text))
            except (ValueError, json.JSONDecodeError):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("ref", "")).strip()[:80]
                req = str(item.get("text", "")).strip()[:400]
                if req:
                    requirements.append(Requirement(ref=ref or "n/a", text=req))
        requirements = requirements[:MAX_REQUIREMENTS]
        await deps.on_requirements(requirements)
        return {"requirements": requirements}

    async def investigate_and_judge(state: AuditState) -> dict[str, Any]:
        done_refs = [f["ref"] for f in state["findings"]]
        findings = list(state["findings"])
        for index, requirement in enumerate(state["requirements"]):
            # Checkpoint semantics: skip what a previous run already judged.
            if index < len(done_refs):
                continue
            embedding = await deps.embedder.embed_query(requirement["text"])
            hits = await deps.store.hybrid_search(
                requirement["text"], embedding, user_id=deps.user.id, k=EVIDENCE_K + 4
            )
            # The regulation must not audit itself.
            hits = [h for h in hits if str(h.document_id) != state["regulation_id"]][:EVIDENCE_K]
            blocks = "\n\n".join(
                f"[{i}] {hit.filename}:\n{hit.content}" for i, hit in enumerate(hits, start=1)
            )
            prompt = (
                f"Requirement ({requirement['ref']}): {requirement['text']}\n\n"
                f"Internal documents:\n\n{blocks if blocks else '(no relevant passage found)'}"
            )
            verdict, rationale, indices = "indeterminate", "", []
            try:
                raw = _json_payload(await ask(_JUDGE_PROMPT, prompt))
                if isinstance(raw, dict):
                    candidate = str(raw.get("verdict", "indeterminate"))
                    if candidate in ("compliant", "gap", "indeterminate"):
                        verdict = candidate
                    rationale = str(raw.get("rationale", ""))[:500]
                    indices = [i for i in raw.get("evidence", []) if isinstance(i, int)]
            except (ValueError, json.JSONDecodeError):
                logger.warning("audit_judge_unparseable", ref=requirement["ref"])
            if not hits:
                verdict = "gap" if verdict == "compliant" else verdict
            evidence = [
                Evidence(filename=hits[i - 1].filename, excerpt=hits[i - 1].content[:300])
                for i in indices
                if 1 <= i <= len(hits)
            ]
            finding = Finding(
                ref=requirement["ref"], verdict=verdict, rationale=rationale, evidence=evidence
            )
            findings.append(finding)
            await deps.on_finding(finding)
        return {"findings": findings}

    async def reporter(state: AuditState) -> dict[str, Any]:
        counts = {"compliant": 0, "gap": 0, "indeterminate": 0}
        for finding in state["findings"]:
            counts[finding["verdict"]] = counts.get(finding["verdict"], 0) + 1
        gaps = [f"{f['ref']}: {f['rationale']}" for f in state["findings"] if f["verdict"] == "gap"]
        prompt = (
            f"Verdicts: {counts}. Gaps:\n" + ("\n".join(gaps[:10]) or "(none)") + "\n\n"
            "Write a 3-5 sentence executive summary of this compliance audit,"
            " in the language of the gaps (or French if none), factual tone,"
            " no recommendations beyond closing the gaps. Plain text only."
        )
        summary = await ask("You are a compliance report writer.", prompt)
        return {"summary": summary.strip()}

    graph = StateGraph(AuditState)
    graph.add_node("cartographer", cartographer)
    graph.add_node("assess", investigate_and_judge)
    graph.add_node("reporter", reporter)
    graph.set_entry_point("cartographer")
    graph.add_edge("cartographer", "assess")
    graph.add_edge("assess", "reporter")
    graph.add_edge("reporter", END)
    return graph.compile()
