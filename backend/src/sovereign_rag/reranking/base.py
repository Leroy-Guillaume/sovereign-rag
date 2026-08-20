"""Reranker Protocol: the precision stage over the fused candidate pool.

Retrieval is recall-then-precision: hybrid search over-fetches a candidate
pool (RERANKER_CANDIDATES), the reranker re-scores every (query, chunk) pair
jointly and keeps the top-k. A reranker can only reorder the pool it is
given, never recover a chunk the first stage missed, which is why the fusion
work happens before this seam and why the control arm (RERANKER_PROVIDER=none)
must stay measurable.
"""

from collections.abc import Sequence
from typing import Protocol

from sovereign_rag.store.base import SearchHit


class Reranker(Protocol):
    """Re-scores fused hits against the query and returns the best k."""

    model: str  # persisted for observability, like LLMClient.model

    async def rerank(self, query: str, hits: Sequence[SearchHit], *, k: int) -> list[SearchHit]:
        """Return the k best hits, re-scored; hits keep their leg ranks."""
        ...
