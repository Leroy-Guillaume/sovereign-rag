"""Integration tests for the ingestion pipeline and the /api/documents endpoints."""

import os
import uuid
from collections.abc import Sequence
from typing import Any, cast

import httpx
import pytest

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings
from sovereign_rag.config import Settings
from sovereign_rag.errors import ProviderError

pytestmark = pytest.mark.integration

ALICE = {"Authorization": "Bearer test-key-alice"}
BOB = {"Authorization": "Bearer test-key-bob"}
ADMIN = {"Authorization": "Bearer test-key-admin"}

_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test")

_MD = (
    b"# Compliance\n"
    b"\n"
    b"All data stays inside your own infrastructure. Nothing leaves the network.\n"
    b"\n"
    b"## Setup\n"
    b"\n"
    b"Run docker compose up, then upload documents through the API.\n"
)


def _settings(**overrides: Any) -> Settings:
    return make_settings(database_url=_DB_URL, **overrides)


def _app_of(client: httpx.AsyncClient) -> Any:
    return cast(Any, client)._transport.app


async def _upload(
    client: httpx.AsyncClient, name: str, data: bytes, headers: dict[str, str]
) -> httpx.Response:
    files = {"file": (name, data, "application/octet-stream")}
    return await client.post("/api/documents", files=files, headers=headers)


class _ExplodingEmbedding:
    """EmbeddingClient whose document embedding always fails.

    Only embed_documents raises: healthcheck and embed_query stay functional
    so the app lifespan (readiness probes, warmup) is not what blows up -
    the failure must happen inside the background ingestion task.
    """

    model = "intfloat/multilingual-e5-small"
    dimensions = 384

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise ProviderError("embedding backend down")

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimensions

    async def healthcheck(self) -> None:
        return None


async def test_upload_md_becomes_ready(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        response = await _upload(client, "notes.md", _MD, ALICE)
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "processing"
        assert body["filename"] == "notes.md"
        assert body["content_type"] == "md"
        assert body["owner_id"] == "alice"

        await _app_of(client).state.ingestion.wait_idle()

        listing = await client.get("/api/documents", headers=ALICE)
        assert listing.status_code == 200
        docs = listing.json()
        assert len(docs) == 1
        assert docs[0]["id"] == body["id"]
        assert docs[0]["status"] == "ready"
        assert docs[0]["error"] is None


async def test_reupload_same_bytes_is_deduplicated(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        first = await _upload(client, "notes.md", _MD, ALICE)
        assert first.status_code == 202
        await _app_of(client).state.ingestion.wait_idle()

        second = await _upload(client, "renamed.md", _MD, ALICE)
        assert second.status_code == 200
        body = second.json()
        assert body["deduplicated"] is True
        assert body["id"] == first.json()["id"]

        listing = await client.get("/api/documents", headers=ALICE)
        assert len(listing.json()) == 1


async def test_upload_unsupported_extension_rejected(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        response = await _upload(client, "malware.exe", b"MZ fake binary", ALICE)
        assert response.status_code == 422


async def test_upload_oversize_rejected(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(max_upload_mb=1),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        response = await _upload(client, "big.txt", b"x" * (1024 * 1024 + 1), ALICE)
        assert response.status_code == 422


async def test_failing_embedder_marks_document_failed(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(),
        llm=FakeLLM(),
        embedder=_ExplodingEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        response = await _upload(client, "notes.md", _MD, ALICE)
        assert response.status_code == 202
        await _app_of(client).state.ingestion.wait_idle()

        listing = await client.get("/api/documents", headers=ALICE)
        doc = listing.json()[0]
        assert doc["status"] == "failed"
        assert "embedding backend down" in doc["error"]


async def test_delete_requires_uploader_or_admin(pg: Any, api_client: Any) -> None:
    store = InMemoryVectorStore()
    embedder = FakeEmbedding()
    async with api_client(
        settings=_settings(), llm=FakeLLM(), embedder=embedder, store=store
    ) as client:
        response = await _upload(client, "notes.md", _MD, ALICE)
        document_id = response.json()["id"]
        await _app_of(client).state.ingestion.wait_idle()

        query_vec = await embedder.embed_query("docker compose")
        hits = await store.hybrid_search("docker compose", query_vec, user_id="alice")
        assert hits, "ingested chunks should be searchable before deletion"

        forbidden = await client.delete(f"/api/documents/{document_id}", headers=BOB)
        assert forbidden.status_code == 403

        deleted = await client.delete(f"/api/documents/{document_id}", headers=ADMIN)
        assert deleted.status_code == 204

        listing = await client.get("/api/documents", headers=ALICE)
        assert listing.json() == []
        assert await store.hybrid_search("docker compose", query_vec, user_id="alice") == []


async def test_delete_unknown_document_returns_404(pg: Any, api_client: Any) -> None:
    async with api_client(
        settings=_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    ) as client:
        response = await client.delete(f"/api/documents/{uuid.uuid4()}", headers=ADMIN)
        assert response.status_code == 404
