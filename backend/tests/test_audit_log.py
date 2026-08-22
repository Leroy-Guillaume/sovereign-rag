"""Append-only audit trail: events from the document routes, admin read, immutability."""

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest
from psycopg.errors import RaiseException
from psycopg_pool import AsyncConnectionPool

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}
AUTH_BOB = {"Authorization": "Bearer test-key-bob"}
AUTH_ADMIN = {"Authorization": "Bearer test-key-admin"}


def _client(api_client: ClientFactory) -> AbstractAsyncContextManager[httpx.AsyncClient]:
    return api_client(
        settings=make_settings(database_url=TEST_DATABASE_URL),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    )


async def test_document_lifecycle_leaves_a_trail(api_client: ClientFactory, pg: Any) -> None:
    async with _client(api_client) as client:
        resp = await client.post(
            "/api/documents",
            files={"file": ("trail.txt", b"audited content", "text/plain")},
            headers=AUTH_ALICE,
        )
        doc_id = resp.json()["id"]
        grant = await client.post(
            f"/api/documents/{doc_id}/permissions",
            json={"principal": "bob"},
            headers=AUTH_ALICE,
        )
        assert grant.status_code == 204
        revoke = await client.delete(f"/api/documents/{doc_id}/permissions/bob", headers=AUTH_ALICE)
        assert revoke.status_code == 204
        deletion = await client.delete(f"/api/documents/{doc_id}", headers=AUTH_ALICE)
        assert deletion.status_code == 204

        trail = (await client.get("/api/admin/audit", headers=AUTH_ADMIN)).json()
    actions = [(e["actor"], e["action"]) for e in trail]
    # Newest first.
    assert actions == [
        ("alice", "document.delete"),
        ("alice", "permission.revoke"),
        ("alice", "permission.grant"),
        ("alice", "document.upload"),
    ]
    by_action = {e["action"]: e for e in trail}
    assert by_action["document.upload"]["detail"]["filename"] == "trail.txt"
    assert by_action["document.upload"]["object_id"] == doc_id
    assert by_action["permission.grant"]["detail"]["principal"] == "bob"
    assert by_action["document.delete"]["detail"]["filename"] == "trail.txt"


async def test_audit_read_requires_admin(api_client: ClientFactory, pg: Any) -> None:
    async with _client(api_client) as client:
        assert (await client.get("/api/admin/audit", headers=AUTH_ALICE)).status_code == 403
        assert (await client.get("/api/admin/audit")).status_code == 401


async def test_audit_rows_cannot_be_rewritten(
    api_client: ClientFactory, pg: AsyncConnectionPool
) -> None:
    """Append-only is a database guarantee, not an application convention."""
    async with _client(api_client) as client:
        await client.post(
            "/api/documents",
            files={"file": ("immutable.txt", b"x", "text/plain")},
            headers=AUTH_ALICE,
        )
    async with pg.connection() as conn:
        with pytest.raises(RaiseException):
            await conn.execute("UPDATE audit_log SET actor = 'mallory'")
    async with pg.connection() as conn:
        with pytest.raises(RaiseException):
            await conn.execute("DELETE FROM audit_log")
