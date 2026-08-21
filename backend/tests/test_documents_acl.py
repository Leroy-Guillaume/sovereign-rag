"""Per-document ACL over the API surface: visibility, sharing, dedupe safety.

Retrieval-level leakage is pinned by the vector-store contract suite; these
tests cover the management surface built on the same rule.
"""

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}
AUTH_BOB = {"Authorization": "Bearer test-key-bob"}
AUTH_ADMIN = {"Authorization": "Bearer test-key-admin"}

pytestmark = pytest.mark.integration


def _client(api_client: ClientFactory) -> AbstractAsyncContextManager[httpx.AsyncClient]:
    return api_client(
        settings=make_settings(database_url=TEST_DATABASE_URL),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    )


async def _upload(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, body: bytes
) -> Any:
    resp = await client.post(
        "/api/documents", files={"file": (name, body, "text/plain")}, headers=headers
    )
    assert resp.status_code in (200, 202), resp.text
    return resp.json()


async def test_uploads_are_private_by_default(api_client: ClientFactory, pg: object) -> None:
    async with _client(api_client) as client:
        doc = await _upload(client, AUTH_ALICE, "private.txt", b"alice private notes")

        alice_list = (await client.get("/api/documents", headers=AUTH_ALICE)).json()
        bob_list = (await client.get("/api/documents", headers=AUTH_BOB)).json()
        admin_list = (await client.get("/api/documents", headers=AUTH_ADMIN)).json()

    assert doc["id"] in {d["id"] for d in alice_list}
    assert doc["id"] not in {d["id"] for d in bob_list}, "a private upload leaked into bob's list"
    assert doc["id"] in {d["id"] for d in admin_list}, "admins keep the management view"


async def test_owner_shares_with_a_named_user_then_revokes(
    api_client: ClientFactory, pg: object
) -> None:
    async with _client(api_client) as client:
        doc = await _upload(client, AUTH_ALICE, "shared.txt", b"alice shares this")
        doc_id = doc["id"]

        # bob cannot share someone else's document
        resp = await client.post(
            f"/api/documents/{doc_id}/permissions", json={"principal": "bob"}, headers=AUTH_BOB
        )
        assert resp.status_code == 403

        # alice shares with bob; bob now sees it listed
        resp = await client.post(
            f"/api/documents/{doc_id}/permissions", json={"principal": "bob"}, headers=AUTH_ALICE
        )
        assert resp.status_code == 204
        bob_list = (await client.get("/api/documents", headers=AUTH_BOB)).json()
        assert doc_id in {d["id"] for d in bob_list}

        perms = (
            await client.get(f"/api/documents/{doc_id}/permissions", headers=AUTH_ALICE)
        ).json()
        assert [(p["principal"], p["granted_by"]) for p in perms] == [("bob", "alice")]

        # revocation closes the door again
        resp = await client.delete(f"/api/documents/{doc_id}/permissions/bob", headers=AUTH_ALICE)
        assert resp.status_code == 204
        bob_list = (await client.get("/api/documents", headers=AUTH_BOB)).json()
        assert doc_id not in {d["id"] for d in bob_list}


async def test_star_grant_opens_to_every_authenticated_user(
    api_client: ClientFactory, pg: object
) -> None:
    async with _client(api_client) as client:
        doc = await _upload(client, AUTH_ALICE, "public.txt", b"alice for everyone")
        resp = await client.post(
            f"/api/documents/{doc['id']}/permissions",
            json={"principal": "*"},
            headers=AUTH_ALICE,
        )
        assert resp.status_code == 204
        bob_list = (await client.get("/api/documents", headers=AUTH_BOB)).json()
    assert doc["id"] in {d["id"] for d in bob_list}


async def test_duplicate_bytes_of_an_invisible_document_conflict(
    api_client: ClientFactory, pg: object
) -> None:
    """The sha256 dedupe must not return another user's private row, and must
    not silently grant access either: 409, explicitly."""
    async with _client(api_client) as client:
        await _upload(client, AUTH_ALICE, "secret.txt", b"identical bytes")
        resp = await client.post(
            "/api/documents",
            files={"file": ("mine.txt", b"identical bytes", "text/plain")},
            headers=AUTH_BOB,
        )
        assert resp.status_code == 409

        # once shared, the same upload dedupes normally again
        alice_docs = (await client.get("/api/documents", headers=AUTH_ALICE)).json()
        doc_id = alice_docs[0]["id"]
        await client.post(
            f"/api/documents/{doc_id}/permissions", json={"principal": "*"}, headers=AUTH_ALICE
        )
        resp = await client.post(
            "/api/documents",
            files={"file": ("mine.txt", b"identical bytes", "text/plain")},
            headers=AUTH_BOB,
        )
        assert resp.status_code == 200
        assert resp.json()["deduplicated"] is True


async def test_permissions_require_owner_or_admin_and_404_on_unknown(
    api_client: ClientFactory, pg: object
) -> None:
    async with _client(api_client) as client:
        doc = await _upload(client, AUTH_ALICE, "managed.txt", b"managed content")
        # admin can manage anyone's permissions
        resp = await client.post(
            f"/api/documents/{doc['id']}/permissions",
            json={"principal": "bob"},
            headers=AUTH_ADMIN,
        )
        assert resp.status_code == 204
        # unknown document
        resp = await client.get(
            "/api/documents/00000000-0000-0000-0000-000000000000/permissions",
            headers=AUTH_ALICE,
        )
        assert resp.status_code == 404
        # malformed principal rejected by the schema
        resp = await client.post(
            f"/api/documents/{doc['id']}/permissions",
            json={"principal": "two words"},
            headers=AUTH_ALICE,
        )
        assert resp.status_code == 422


async def test_listing_reports_chunk_count(api_client: ClientFactory, pg: Any) -> None:
    """GET /api/documents counts the rows actually indexed in the chunks table
    (the admin table renders it as "ready - N passages")."""
    async with _client(api_client) as client:
        doc = await _upload(client, AUTH_ALICE, "counted.txt", b"counted content")
        zero_vector = "[" + ",".join(["0"] * 384) + "]"
        async with pg.connection() as conn:
            for index in range(3):
                await conn.execute(
                    """INSERT INTO chunks (document_id, chunk_index, content, embedding)
                       VALUES (%s, %s, %s, %s::vector)""",
                    (doc["id"], index, f"chunk {index}", zero_vector),
                )
        listing = (await client.get("/api/documents", headers=AUTH_ALICE)).json()
    by_id = {d["id"]: d for d in listing}
    assert by_id[doc["id"]]["chunk_count"] == 3
