"""Compliance audits: lifecycle, ownership, single-flight, checkpoint resume."""

import asyncio
import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from fakes import FakeEmbedding, InMemoryVectorStore, make_settings
from sovereign_rag.store.base import ChunkIn
from test_deep_graph import ScriptedLLM

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}
AUTH_BOB = {"Authorization": "Bearer test-key-bob"}

ZERO_VECTOR = "[" + ",".join(["0"] * 384) + "]"

MAP_JSON = (
    '[{"ref": "art. 8", "text": "Assurer une securite adaptee au risque."},'
    ' {"ref": "art. 24", "text": "Annoncer les violations au PFPDT."}]'
)
COMPLIANT_JSON = (
    '{"verdict": "compliant", "rationale": "La politique interne couvre ce point.",'
    ' "evidence": [1]}'
)
GAP_JSON = '{"verdict": "gap", "rationale": "Aucune procedure d\'annonce.", "evidence": []}'


def _app_state(client: httpx.AsyncClient) -> Any:
    return client._transport.app.state  # type: ignore[attr-defined] # pyright: ignore[reportAttributeAccessIssue]


async def _seed_regulation(
    client: httpx.AsyncClient, pg: AsyncConnectionPool, headers: dict[str, str]
) -> str:
    resp = await client.post(
        "/api/documents",
        files={"file": ("nlpd.txt", b"art 8 securite; art 24 annonce", "text/plain")},
        headers=headers,
    )
    doc_id = resp.json()["id"]
    await _app_state(client).ingestion.wait_idle()
    async with pg.connection() as conn:
        for index, content in enumerate(["Art. 8 securite adaptee.", "Art. 24 annonce PFPDT."]):
            await conn.execute(
                """INSERT INTO chunks (document_id, chunk_index, content, embedding)
                   VALUES (%s, %s, %s, %s::vector)""",
                (doc_id, index, content, ZERO_VECTOR),
            )
    return doc_id


async def _seed_internal_policy(store: InMemoryVectorStore, embedder: FakeEmbedding) -> None:
    content = "Politique interne: mesures de securite conformes au risque."
    embeddings = await embedder.embed_documents([content])
    doc = uuid4()
    await store.add_chunks(doc, [ChunkIn(chunk_index=0, content=content, embedding=embeddings[0])])
    store.owners[doc] = "alice"


async def _wait_completed(client: httpx.AsyncClient, audit_id: str) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for _ in range(100):
        detail = (await client.get(f"/api/audits/{audit_id}", headers=AUTH_ALICE)).json()
        if detail["status"] in ("completed", "failed"):
            return detail
        await asyncio.sleep(0.05)
    raise AssertionError(f"audit never settled: {detail}")


def _client(
    api_client: ClientFactory, llm: ScriptedLLM, store: InMemoryVectorStore, embedder: FakeEmbedding
):
    return api_client(
        settings=make_settings(database_url=TEST_DATABASE_URL),
        llm=llm,
        embedder=embedder,
        store=store,
    )


async def test_audit_runs_to_completion_with_findings(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    await _seed_internal_policy(store, embedder)
    llm = ScriptedLLM([MAP_JSON, COMPLIANT_JSON, GAP_JSON, "Deux exigences, un ecart."])
    async with _client(api_client, llm, store, embedder) as client:
        doc_id = await _seed_regulation(client, pg, AUTH_ALICE)
        resp = await client.post("/api/audits", json={"regulation_id": doc_id}, headers=AUTH_ALICE)
        assert resp.status_code == 202, resp.text
        audit_id = resp.json()["id"]
        detail = await _wait_completed(client, audit_id)
        assert detail["status"] == "completed"
        assert detail["requirements_total"] == 2
        assert detail["findings_done"] == 2
        assert detail["gaps"] == 1
        assert detail["summary"] == "Deux exigences, un ecart."
        verdicts = {f["ref"]: f["verdict"] for f in detail["findings"]}
        assert verdicts == {"art. 8": "compliant", "art. 24": "gap"}
        # The compliant finding cites the internal policy, not the regulation.
        evidence = detail["findings"][0]["evidence"]
        assert evidence, "compliant verdict must carry its evidence"
        assert "Politique interne" in evidence[0]["excerpt"]

        listing = (await client.get("/api/audits", headers=AUTH_ALICE)).json()
        assert [a["id"] for a in listing] == [audit_id]
        # Foreign eyes see nothing: list empty, detail 404.
        assert (await client.get("/api/audits", headers=AUTH_BOB)).json() == []
        assert (await client.get(f"/api/audits/{audit_id}", headers=AUTH_BOB)).status_code == 404


async def test_single_audit_at_a_time_per_owner(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    llm = ScriptedLLM([MAP_JSON, COMPLIANT_JSON, GAP_JSON, "resume"])
    async with _client(api_client, llm, store, embedder) as client:
        doc_id = await _seed_regulation(client, pg, AUTH_ALICE)
        async with pg.connection() as conn:
            await conn.execute(
                """INSERT INTO audits (owner_id, regulation_id, regulation_filename, status)
                   VALUES ('alice', %s, 'nlpd.txt', 'running')""",
                (doc_id,),
            )
        resp = await client.post("/api/audits", json={"regulation_id": doc_id}, headers=AUTH_ALICE)
        assert resp.status_code == 409


async def test_resume_continues_from_the_checkpoint(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    """A row left 'running' with one finding resumes at requirement two: the
    script contains NO cartographer reply, so any re-extraction would fail."""
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    await _seed_internal_policy(store, embedder)
    llm = ScriptedLLM([GAP_JSON, "Reprise terminee."])
    async with _client(api_client, llm, store, embedder) as client:
        doc_id = await _seed_regulation(client, pg, AUTH_ALICE)
        audit_id = uuid4()
        async with pg.connection() as conn:
            await conn.execute(
                """INSERT INTO audits
                   (id, owner_id, regulation_id, regulation_filename, status,
                    requirements, findings)
                   VALUES (%s, 'alice', %s, 'nlpd.txt', 'running', %s, %s)""",
                (
                    audit_id,
                    doc_id,
                    Jsonb(
                        [
                            {"ref": "art. 8", "text": "Securite adaptee."},
                            {"ref": "art. 24", "text": "Annonce PFPDT."},
                        ]
                    ),
                    Jsonb(
                        [
                            {
                                "ref": "art. 8",
                                "verdict": "compliant",
                                "rationale": "deja juge",
                                "evidence": [],
                            }
                        ]
                    ),
                ),
            )
        resumed = await _app_state(client).audits.resume_interrupted()
        assert resumed == 1
        detail = await _wait_completed(client, str(audit_id))
        assert detail["status"] == "completed"
        assert detail["findings_done"] == 2
        assert detail["findings"][0]["rationale"] == "deja juge"  # untouched checkpoint
        assert detail["findings"][1]["verdict"] == "gap"
        assert detail["summary"] == "Reprise terminee."
