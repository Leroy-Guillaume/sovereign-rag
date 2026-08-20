"""Contract suite for VectorStore implementations.

The same behavioural tests run against two implementations:

- InMemoryVectorStore (tests/fakes.py): pure Python, no marker, runs everywhere.
- PgVectorStore: real Postgres + pgvector, marked "integration"; skipped
  automatically when TEST_DATABASE_URL is unreachable (see the pg fixture).

Both implementations use rrf_k=60 and per-leg candidates=40, so fused scores are
exactly 1/(60+vec_rank) + 1/(60+fts_rank), a missing leg contributing 0.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from fakes import InMemoryVectorStore, make_settings
from sovereign_rag.store import get_vector_store
from sovereign_rag.store.base import ChunkIn, VectorStore
from sovereign_rag.store.pgvector import PgVectorStore

DIMS = 384  # must match vector(384) in migrations/0001_schema.sql

BOTH_LEGS = "encryption of backups requires encryption keys and encryption policies"
ONE_MATCH = "the encryption module is optional"
NO_MATCH = "quarterly pastry budget review meeting notes"

FR_CHUNK = "le chiffrement des données personnelles est obligatoire selon la nlpd"
DE_CHUNK = "der datenschutz gilt für alle personenbezogenen daten in der schweiz"
EN_CHUNK = "encryption of personal data is mandatory under swiss law"


def basis(i: int) -> list[float]:
    """Unit basis vector e_i in DIMS dimensions."""
    vec = [0.0] * DIMS
    vec[i] = 1.0
    return vec


def blend(i: int, j: int, wi: float, wj: float) -> list[float]:
    """L2-normalized wi*e_i + wj*e_j; cosine similarity with e_i is wi/sqrt(wi^2+wj^2)."""
    norm = math.sqrt(wi * wi + wj * wj)
    vec = [0.0] * DIMS
    vec[i] = wi / norm
    vec[j] = wj / norm
    return vec


class MakeDocument(Protocol):
    """Create a document (status='ready') the store can attach chunks to."""

    def __call__(self) -> Awaitable[UUID]: ...


class MakePrivateDocument(Protocol):
    """Create a ready document owned by `owner`, with no permission rows."""

    def __call__(self, owner: str) -> Awaitable[UUID]: ...


class Grant(Protocol):
    """Grant read access on a document to a principal ('*' = everyone)."""

    def __call__(self, document_id: UUID, principal: str) -> Awaitable[None]: ...


class VectorStoreContract:
    """Behavioural contract shared by every VectorStore implementation.

    Subclasses provide the `store` and `new_document` fixtures.
    """

    async def test_chunk_matching_both_legs_ranks_first_with_rrf_score(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        doc_id = await new_document()
        await store.add_chunks(
            doc_id,
            [
                # cosine sim 1.0 -> vec rank 1; 3x "encryption" -> fts rank 1
                ChunkIn(0, BOTH_LEGS, basis(0)),
                # cosine sim 0.6 -> vec rank 2; 1x "encryption" -> fts rank 2
                ChunkIn(1, ONE_MATCH, blend(0, 1, 3.0, 4.0)),
                # cosine sim ~0.447 -> vec rank 3; no query term -> no fts rank
                ChunkIn(2, NO_MATCH, blend(0, 2, 1.0, 2.0)),
            ],
        )

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)

        assert [hit.content for hit in hits] == [BOTH_LEGS, ONE_MATCH, NO_MATCH]
        assert hits[0].document_id == doc_id
        assert hits[0].vec_rank == 1
        assert hits[0].fts_rank == 1
        assert hits[0].score == pytest.approx(1 / (60 + 1) + 1 / (60 + 1))
        assert hits[1].score == pytest.approx(1 / (60 + 2) + 1 / (60 + 2))
        assert hits[2].score == pytest.approx(1 / (60 + 3))

    async def test_k_is_respected(self, store: VectorStore, new_document: MakeDocument) -> None:
        # One chunk per document so the per-document cap never interferes:
        # this test is about k, nothing else.
        for i in range(5):
            doc_id = await new_document()
            await store.add_chunks(
                doc_id,
                [ChunkIn(0, f"encryption note {i}", blend(0, i + 1, 10.0 - i, 1.0 + i))],
            )

        assert len(await store.hybrid_search("encryption", basis(0), user_id="a", k=3)) == 3
        assert len(await store.hybrid_search("encryption", basis(0), user_id="a", k=8)) == 5

    async def test_per_document_cap_diversifies_results(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        # Five near-identical chunks in one document, one relevant chunk in a
        # second document: the cap (default 3) must leave room for the second
        # document instead of letting the first flood the top-k.
        flood_id = await new_document()
        await store.add_chunks(
            flood_id,
            [
                ChunkIn(i, f"encryption policy clause {i}", blend(0, i + 1, 20.0, 1.0))
                for i in range(5)
            ],
        )
        other_id = await new_document()
        await store.add_chunks(other_id, [ChunkIn(0, "encryption addendum", blend(0, 9, 8.0, 6.0))])

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)

        per_doc = Counter(hit.document_id for hit in hits)
        assert per_doc[flood_id] == 3, "the flooding document must be capped at 3 chunks"
        assert per_doc[other_id] == 1, "the capped slots must go to the other document"

    async def test_sentence_question_still_reaches_fts(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        # A question phrased as a full sentence must still produce lexical
        # candidates: the informative terms are extracted and, when no chunk
        # holds all of them, the relaxed any-term fallback engages. This is
        # the exact scenario the raw tri-config AND query matched nothing on.
        doc_id = await new_document()
        await store.add_chunks(
            doc_id,
            [ChunkIn(0, "le chiffrement des sauvegardes est obligatoire", basis(5))],
        )

        hits = await store.hybrid_search(
            "comment fonctionne le chiffrement pour les sauvegardes ?", basis(0), user_id="a", k=8
        )

        assert hits, "sentence-shaped query returned no hits"
        assert hits[0].fts_rank == 1, "the lexical leg did not surface the matching chunk"

    async def test_vector_only_hit_has_no_fts_rank(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        doc_id = await new_document()
        await store.add_chunks(
            doc_id,
            [
                ChunkIn(0, "encryption policy overview", blend(0, 1, 1.0, 1.0)),
                ChunkIn(1, NO_MATCH, basis(0)),  # closest to the query, no query term
            ],
        )

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)

        vec_only = next(hit for hit in hits if hit.content == NO_MATCH)
        assert vec_only.vec_rank == 1
        assert vec_only.fts_rank is None
        assert vec_only.score == pytest.approx(1 / (60 + 1))
        # 1/(60+2) + 1/(60+1) beats 1/(60+1): the both-legs chunk still wins.
        assert hits[0].content == "encryption policy overview"

    async def test_fts_only_hit_has_no_vec_rank(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        # 41 fillers closer to the query push the keyword chunk out of the vector
        # leg (per-leg candidates=40); it can only be found by full-text search.
        doc_id = await new_document()
        fillers = [
            ChunkIn(i, f"filler note {i} about warehouse logistics", blend(0, i + 1, 9.0, 1.0))
            for i in range(41)
        ]
        target = ChunkIn(41, "encryption keys are stored in the vault", basis(383))
        await store.add_chunks(doc_id, [*fillers, target])

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=42)

        matching = [hit for hit in hits if "encryption" in hit.content]
        assert len(matching) == 1
        assert matching[0].vec_rank is None
        assert matching[0].fts_rank == 1
        assert matching[0].score == pytest.approx(1 / (60 + 1))

    async def test_two_principal_leakage(
        self,
        store: VectorStore,
        new_private_document: MakePrivateDocument,
    ) -> None:
        # The core ACL guarantee: bob's private document is invisible to alice
        # through EVERY leg (the chunk matches the query lexically and is the
        # vector nearest-neighbour), while bob keeps full access.
        bob_doc = await new_private_document("bob")
        await store.add_chunks(bob_doc, [ChunkIn(0, "encryption secret clause", basis(0))])

        assert await store.hybrid_search("encryption", basis(0), user_id="alice", k=8) == []
        bob_hits = await store.hybrid_search("encryption", basis(0), user_id="bob", k=8)
        assert [hit.content for hit in bob_hits] == ["encryption secret clause"]

    async def test_grants_open_access_to_the_named_principal_or_everyone(
        self,
        store: VectorStore,
        new_private_document: MakePrivateDocument,
        grant: Grant,
    ) -> None:
        named = await new_private_document("bob")
        await store.add_chunks(named, [ChunkIn(0, "encryption named grant", basis(0))])
        starred = await new_private_document("bob")
        await store.add_chunks(starred, [ChunkIn(0, "encryption star grant", basis(1))])
        await grant(named, "alice")
        await grant(starred, "*")

        alice = {
            h.content
            for h in await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)
        }
        carol = {
            h.content
            for h in await store.hybrid_search("encryption", basis(0), user_id="carol", k=8)
        }
        assert alice == {"encryption named grant", "encryption star grant"}
        assert carol == {"encryption star grant"}, "a named grant must not leak to third parties"

    async def test_french_german_english_queries_each_hit(
        self, store: VectorStore, new_document: MakeDocument
    ) -> None:
        # Tri-config proof: one keyword per language, each query must match via FTS.
        # The query embedding is orthogonal to every chunk, so the vector leg cannot
        # explain a first-place hit: 1/(60+1) fts + worst-case 1/(60+3) vec always
        # beats a vec-only 1/(60+1).
        doc_id = await new_document()
        await store.add_chunks(
            doc_id,
            [
                ChunkIn(0, FR_CHUNK, basis(5)),
                ChunkIn(1, DE_CHUNK, basis(6)),
                ChunkIn(2, EN_CHUNK, basis(7)),
            ],
        )

        for query, expected in [
            ("chiffrement", FR_CHUNK),
            ("datenschutz", DE_CHUNK),
            ("encryption", EN_CHUNK),
        ]:
            hits = await store.hybrid_search(query, basis(0), user_id="alice", k=8)
            assert hits, f"query {query!r} returned no hits"
            assert hits[0].content == expected, f"query {query!r} did not rank its chunk first"
            assert hits[0].fts_rank == 1, f"query {query!r} did not match via FTS"


async def test_get_vector_store_builds_pgvector_from_settings() -> None:
    settings = make_settings()
    # open=False: the pool object is inert, nothing ever connects. The explicit
    # annotation is for pyright: psycopg_pool's connection_class default keeps
    # the pool's connection TypeVar unsolved without a declared type.
    pool: AsyncConnectionPool = AsyncConnectionPool(settings.database_url, open=False)
    try:
        store = get_vector_store(settings, pool)
        assert isinstance(store, PgVectorStore)
    finally:
        await pool.close()


class TestInMemoryVectorStoreContract(VectorStoreContract):
    """Unit leg: pure-Python fake, no external services, no marker."""

    @pytest.fixture
    def store(self) -> InMemoryVectorStore:
        return InMemoryVectorStore()

    @pytest.fixture
    def new_document(self) -> MakeDocument:
        async def _new() -> UUID:
            # The fake needs no prior registration: it tracks documents via add_chunks.
            return uuid4()

        return _new

    @pytest.fixture
    def new_private_document(self, store: InMemoryVectorStore) -> MakePrivateDocument:
        async def _new(owner: str) -> UUID:
            doc_id = uuid4()
            store.owners[doc_id] = owner
            return doc_id

        return _new

    @pytest.fixture
    def grant(self, store: InMemoryVectorStore) -> Grant:
        async def _grant(document_id: UUID, principal: str) -> None:
            store.permissions.setdefault(document_id, set()).add(principal)

        return _grant


INSERT_DOCUMENT = """\
INSERT INTO documents (id, filename, content_type, sha256, size_bytes, status, owner_id)
VALUES (%(id)s, %(filename)s, 'txt', %(sha256)s, 42, %(status)s, %(owner)s)
"""

INSERT_PERMISSION = """\
INSERT INTO document_permissions (document_id, principal, granted_by)
VALUES (%(document_id)s, %(principal)s, 'contract-test')
"""


async def _insert_document(
    pool: AsyncConnectionPool,
    *,
    filename: str,
    status: str,
    owner: str = "alice",
    share_all: bool = True,
) -> UUID:
    """Insert a documents row directly; the ingestion service does not exist yet.

    share_all mirrors Phase 1 visibility (a '*' permission row) so the legacy
    contract fixtures keep passing whichever user_id a test searches with; the
    ACL tests insert private documents by turning it off.
    """
    doc_id = uuid4()
    async with pool.connection() as conn:
        await conn.execute(
            INSERT_DOCUMENT,
            {
                "id": doc_id,
                "filename": filename,
                "sha256": uuid4().hex,
                "status": status,
                "owner": owner,
            },
        )
        if share_all:
            await conn.execute(INSERT_PERMISSION, {"document_id": doc_id, "principal": "*"})
    return doc_id


@pytest.mark.integration
class TestPgVectorStoreContract(VectorStoreContract):
    """Integration leg: real Postgres; the pg fixture skips when the DB is unreachable."""

    @pytest.fixture
    async def store(self, pg: AsyncConnectionPool) -> PgVectorStore:
        return PgVectorStore(pg, candidates=40, rrf_k=60, ef_search=80)

    @pytest.fixture
    async def new_document(self, pg: AsyncConnectionPool) -> MakeDocument:
        async def _new() -> UUID:
            return await _insert_document(pg, filename="doc.txt", status="ready")

        return _new

    @pytest.fixture
    async def new_private_document(self, pg: AsyncConnectionPool) -> MakePrivateDocument:
        async def _new(owner: str) -> UUID:
            return await _insert_document(
                pg, filename="private.txt", status="ready", owner=owner, share_all=False
            )

        return _new

    @pytest.fixture
    async def grant(self, pg: AsyncConnectionPool) -> Grant:
        async def _grant(document_id: UUID, principal: str) -> None:
            async with pg.connection() as conn:
                await conn.execute(
                    INSERT_PERMISSION, {"document_id": document_id, "principal": principal}
                )

        return _grant

    async def test_processing_document_excluded_from_both_legs(
        self, store: PgVectorStore, pg: AsyncConnectionPool
    ) -> None:
        ready_id = await _insert_document(pg, filename="ready.txt", status="ready")
        wip_id = await _insert_document(pg, filename="wip.txt", status="processing")
        await store.add_chunks(
            ready_id, [ChunkIn(0, "encryption policy for backups", blend(0, 1, 8.0, 1.0))]
        )
        # Closest embedding AND a keyword match: would win both legs if not filtered.
        await store.add_chunks(wip_id, [ChunkIn(0, "encryption master key handling", basis(0))])

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)

        assert len(hits) == 1
        assert hits[0].document_id == ready_id
        assert hits[0].filename == "ready.txt"

    async def test_delete_document_cascades_chunks_out_of_results(
        self, store: PgVectorStore, pg: AsyncConnectionPool
    ) -> None:
        doc_id = await _insert_document(pg, filename="gone.txt", status="ready")
        await store.add_chunks(
            doc_id,
            [
                ChunkIn(0, "encryption at rest", basis(0)),
                ChunkIn(1, "encryption in transit", basis(1)),
            ],
        )
        assert len(await store.hybrid_search("encryption", basis(0), user_id="a", k=8)) == 2

        await store.delete_document(doc_id)

        assert await store.hybrid_search("encryption", basis(0), user_id="a", k=8) == []
        async with pg.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) FROM chunks WHERE document_id = %s", (doc_id,)
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 0

    async def test_hit_fields_round_trip(
        self, store: PgVectorStore, pg: AsyncConnectionPool
    ) -> None:
        doc_id = await _insert_document(pg, filename="guide.pdf", status="ready")
        await store.add_chunks(
            doc_id,
            [
                ChunkIn(
                    3,
                    "encryption checklist for auditors",
                    basis(0),
                    section="Setup > Docker",
                    page=7,
                )
            ],
        )

        hits = await store.hybrid_search("encryption", basis(0), user_id="alice", k=8)

        assert len(hits) == 1
        hit = hits[0]
        assert isinstance(hit.chunk_id, UUID)
        assert hit.document_id == doc_id
        assert hit.filename == "guide.pdf"
        assert hit.section == "Setup > Docker"
        assert hit.page == 7
        assert hit.content == "encryption checklist for auditors"

    async def test_ef_search_is_set_locally_inside_the_search_transaction(
        self, pg: AsyncConnectionPool
    ) -> None:
        store = PgVectorStore(pg, candidates=40, rrf_k=60, ef_search=57)
        doc_id = await _insert_document(pg, filename="ef.txt", status="ready")
        await store.add_chunks(doc_id, [ChunkIn(0, "encryption knob probe", basis(0))])

        # Drive the exact code path hybrid_search uses, but inside a transaction we
        # own, so SHOW can observe the SET LOCAL before it is reverted at commit.
        async with pg.connection() as conn:
            await register_vector_async(conn)
            async with conn.transaction():
                rows = await store._search_in_tx(  # pyright: ignore[reportPrivateUsage]
                    conn, "encryption", basis(0), user_id="alice", k=8
                )
                cur = await conn.execute("SHOW hnsw.ef_search")
                shown = await cur.fetchone()
        assert len(rows) == 1
        assert shown is not None
        assert shown[0] == "57"

        # SET LOCAL must not leak outside the transaction (pooled conns are reused).
        async with pg.connection() as conn:
            # Touch the vector type first: on a fresh backend the hnsw.* GUCs only
            # exist once pgvector's library is loaded, and SHOW would error out.
            await conn.execute("SELECT '[1]'::vector")
            cur = await conn.execute("SHOW hnsw.ef_search")
            after = await cur.fetchone()
        assert after is not None
        assert after[0] != "57"
