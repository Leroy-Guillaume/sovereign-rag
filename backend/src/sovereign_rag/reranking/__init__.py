"""Reranker factory.

Same shape as the LLM/embedding factories: lazy import per branch,
assert_never for exhaustiveness. Returns None for the "none" provider, which
is the control arm: the chat service then serves the fused order directly.
"""

from typing import assert_never

from sovereign_rag.config import Settings
from sovereign_rag.reranking.base import Reranker

__all__ = ["Reranker", "get_reranker"]


def get_reranker(settings: Settings) -> Reranker | None:
    match settings.reranker_provider:
        case "none":
            return None
        case "local":
            from sovereign_rag.reranking.local import LocalCrossEncoderReranker

            return LocalCrossEncoderReranker(settings)
        case _:
            assert_never(settings.reranker_provider)
