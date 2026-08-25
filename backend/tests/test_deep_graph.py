"""Deep-search graph: routing, bounded repairs, abstention, with a scripted LLM."""

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from fakes import FakeEmbedding, InMemoryVectorStore, make_settings
from sovereign_rag.agents.graph import DeepDeps, build_deep_graph, initial_state
from sovereign_rag.auth import User
from sovereign_rag.llm.base import ChatMessage, CompletionChunk
from sovereign_rag.store.base import ChunkIn


class ScriptedLLM:
    """Returns the next scripted reply on each call; records the prompts."""

    model = "scripted/llm"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[CompletionChunk]:
        self.prompts.append(messages[0].content)
        reply = self.replies.pop(0)

        async def gen() -> AsyncIterator[CompletionChunk]:
            yield CompletionChunk(delta=reply)
            yield CompletionChunk(delta="", prompt_tokens=1, completion_tokens=1)

        return gen()

    async def healthcheck(self) -> None:
        return None


async def _deps(llm: ScriptedLLM, steps: list[tuple[str, str]]) -> DeepDeps:
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    contents = [
        "La nLPD impose des mesures de securite adaptees au risque.",
        "L'annonce au PFPDT doit intervenir dans les meilleurs delais.",
    ]
    embeddings = await embedder.embed_documents(contents)
    await store.add_chunks(
        uuid4(),
        [
            ChunkIn(chunk_index=i, content=c, embedding=e)
            for i, (c, e) in enumerate(zip(contents, embeddings, strict=True))
        ],
    )

    async def emit(agent: str, detail: str) -> None:
        steps.append((agent, detail))

    return DeepDeps(
        llm=llm,
        embedder=embedder,
        store=store,
        reranker=None,
        settings=make_settings(),
        user=User(id="alice", roles=frozenset()),
        emit=emit,
    )


async def test_happy_path_delivers_with_all_supported(pg: Any) -> None:
    llm = ScriptedLLM(
        [
            '["securite nLPD", "delais annonce PFPDT"]',  # plan
            "Les mesures [1] et l'annonce [2].",  # write
            '[{"text": "mesures", "verdict": "supported", "fix_query": ""}]',  # verify
        ]
    )
    steps: list[tuple[str, str]] = []
    graph = build_deep_graph(await _deps(llm, steps))
    final = await graph.ainvoke(initial_state("Question a deux volets ?"))
    assert final["outcome"] == "delivered"
    assert final["draft"] == "Les mesures [1] et l'annonce [2]."
    assert len(final["evidence"]) == 2
    assert [agent for agent, _ in steps] == ["planner", "searcher", "writer", "verifier"]


async def test_unsupported_claim_routes_back_to_search_once(pg: Any) -> None:
    llm = ScriptedLLM(
        [
            '["axe unique"]',  # plan
            "Premiere version [1].",  # write 1
            '[{"text": "x", "verdict": "unsupported", "fix_query": "delais PFPDT"}]',  # verify 1
            "Version corrigee [1][2].",  # write 2 (after repair search)
            '[{"text": "x", "verdict": "supported", "fix_query": ""}]',  # verify 2
        ]
    )
    steps: list[tuple[str, str]] = []
    graph = build_deep_graph(await _deps(llm, steps))
    final = await graph.ainvoke(initial_state("Question ?"))
    assert final["outcome"] == "delivered"
    assert final["draft"] == "Version corrigee [1][2]."
    assert final["search_repairs"] == 1
    # The repair searched the verifier's targeted query.
    agents = [agent for agent, _ in steps]
    assert agents.count("searcher") == 2


async def test_all_unanswerable_abstains(pg: Any) -> None:
    llm = ScriptedLLM(
        [
            '["hors corpus"]',
            "Tentative [1].",
            '[{"text": "y", "verdict": "unanswerable", "fix_query": ""}]',
        ]
    )
    steps: list[tuple[str, str]] = []
    graph = build_deep_graph(await _deps(llm, steps))
    final = await graph.ainvoke(initial_state("Question hors corpus ?"))
    assert final["outcome"] == "abstained"
    assert final["evidence"] == []
    assert final["draft"] == ""


async def test_repair_budget_is_bounded(pg: Any) -> None:
    """A verifier that never approves cannot loop forever: two search
    repairs, then the single replan, then the best-effort draft ships."""
    unsup = '[{"text": "x", "verdict": "unsupported", "fix_query": "q"}]'
    llm = ScriptedLLM(
        [
            '["axe"]',  # plan 1
            "V1 [1].",
            unsup,  # -> search repair 1
            "V2 [1].",
            unsup,  # -> search repair 2
            "V3 [1].",
            unsup,  # search budget exhausted -> replan
            '["axe reformule"]',  # plan 2
            "V4 [1].",
            unsup,  # all budgets exhausted -> deliver best effort
        ]
    )
    graph = build_deep_graph(await _deps(llm, []))
    final = await graph.ainvoke(initial_state("Question ?"))
    assert final["outcome"] == "delivered"
    assert final["search_repairs"] == 2
    assert final["replans"] == 1
    assert final["draft"] == "V4 [1]."


async def test_deep_search_respects_the_caller_acl(pg: Any) -> None:
    """The graph's searcher goes through the store with the caller's id:
    another user's private document must never surface in deep evidence."""
    llm = ScriptedLLM(
        [
            '["question"]',
            "Reponse [1].",
            '[{"text": "ok", "verdict": "supported", "fix_query": ""}]',
        ]
    )
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    shared_doc, private_doc = uuid4(), uuid4()
    contents = ["Document partage sur la nLPD.", "Document PRIVE de bob sur la nLPD."]
    embeddings = await embedder.embed_documents(contents)
    await store.add_chunks(
        shared_doc, [ChunkIn(chunk_index=0, content=contents[0], embedding=embeddings[0])]
    )
    await store.add_chunks(
        private_doc, [ChunkIn(chunk_index=0, content=contents[1], embedding=embeddings[1])]
    )
    store.owners[shared_doc] = "alice"
    store.owners[private_doc] = "bob"  # no grant to alice, no wildcard

    steps: list[tuple[str, str]] = []

    async def emit(agent: str, detail: str) -> None:
        steps.append((agent, detail))

    deps = DeepDeps(
        llm=llm,
        embedder=embedder,
        store=store,
        reranker=None,
        settings=make_settings(),
        user=User(id="alice", roles=frozenset()),
        emit=emit,
    )
    graph = build_deep_graph(deps)
    final = await graph.ainvoke(initial_state("Que dit la nLPD ?"))
    assert final["outcome"] == "delivered"
    contents_seen = [hit.content for hit in final["evidence"]]
    assert any("partage" in c for c in contents_seen)
    assert not any("PRIVE" in c for c in contents_seen), (
        "bob's private doc leaked into deep evidence"
    )
