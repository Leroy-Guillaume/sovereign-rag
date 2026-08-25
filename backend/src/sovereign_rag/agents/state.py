"""Typed state carried through the deep-search graph."""

from typing import Literal, TypedDict

from ..store.base import SearchHit

# Verdict a claim can receive from the verifier, with its routing meaning:
#   supported        -> nothing to do
#   misattributed    -> the evidence exists but the citation is wrong: WRITER
#   unsupported      -> evidence missing: SEARCHER with a targeted query
#   unanswerable     -> the corpus does not cover this axis: abstain if global
ClaimVerdict = Literal["supported", "misattributed", "unsupported", "unanswerable"]

MAX_SEARCH_REPAIRS = 2
MAX_WRITE_REPAIRS = 2
MAX_REPLANS = 1


class Claim(TypedDict):
    text: str
    verdict: ClaimVerdict
    fix_query: str  # the targeted query when verdict == "unsupported"


class DeepState(TypedDict):
    question: str
    # PLANNER output: 1-4 sub-questions in the question's language.
    plan: list[str]
    # SEARCHER output: deduplicated evidence across all sub-questions,
    # numbered in order for the writer's [n] citations.
    evidence: list[SearchHit]
    # Extra targeted queries requested by the verifier (repair loop).
    pending_queries: list[str]
    draft: str
    claims: list[Claim]
    search_repairs: int
    write_repairs: int
    replans: int
    outcome: Literal["", "delivered", "abstained"]
