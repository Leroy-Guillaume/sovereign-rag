"""Seed proof: SEED_DEMO_DATA=true ingests data/demo/ at boot and makes it searchable.

Integration tests -- they require a reachable Postgres (TEST_DATABASE_URL) and skip
cleanly otherwise, like every test using the ``pg`` fixture. The app is booted with
FakeEmbedding + FakeLLM but the REAL PgVectorStore, so the whole seed path
(extract -> chunk -> embed -> insert -> hybrid_search) is exercised against a real
Postgres with pgvector.

The corpus mixes formats on purpose (2 markdown + 1 PDF): the PDF forces the pypdf
extraction path to run inside the boot seed and is the only source of chunks carrying
a page number, i.e. of page-level citations in the demo.
"""

import os
from pathlib import Path

import pytest

from fakes import FakeEmbedding, FakeLLM, make_settings
from sovereign_rag.main import create_app

pytestmark = pytest.mark.integration

DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)


async def test_seed_ingests_demo_corpus(pg: object) -> None:
    embedder = FakeEmbedding()
    app = create_app(
        settings=make_settings(
            database_url=TEST_DATABASE_URL,
            seed_demo_data=True,
            demo_data_dir=str(DEMO_DIR),
        ),
        llm=FakeLLM(),
        embedder=embedder,
    )
    async with app.router.lifespan_context(app):
        await app.state.ingestion.wait_idle()

        async with app.state.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT filename, status, error FROM documents ORDER BY filename"
            )
            rows = await cur.fetchall()
        assert len(rows) == 3, f"expected 3 seeded documents, got {rows}"
        assert all(row[1] == "ready" for row in rows), f"not all documents ready: {rows}"
        assert [row[0] for row in rows] == [
            "dsg-auszug.de.md",
            "iso27001-overview.en.pdf",
            "nlpd-excerpt.fr.md",
        ]

        query_vec = await embedder.embed_query("données personnelles")
        hits = await app.state.store.hybrid_search(
            "données personnelles", query_vec, user_id="alice", k=8
        )
        assert hits, "hybrid_search returned no hits on the seeded demo corpus"
        assert any(hit.filename == "nlpd-excerpt.fr.md" for hit in hits), (
            f"expected a hit from the French nLPD excerpt, got {[h.filename for h in hits]}"
        )


async def test_seed_pdf_produces_page_level_citations(pg: object) -> None:
    """The demo corpus is not markdown-only: the PDF goes through pypdf at boot.

    Two proofs: chunks of the seeded PDF carry a page number (extraction ran and
    the page survived chunking), and a hybrid_search hit on that PDF exposes it --
    which is exactly what feeds SourceOut.page in the demo UI.
    """
    embedder = FakeEmbedding()
    app = create_app(
        settings=make_settings(
            database_url=TEST_DATABASE_URL,
            seed_demo_data=True,
            demo_data_dir=str(DEMO_DIR),
        ),
        llm=FakeLLM(),
        embedder=embedder,
    )
    async with app.router.lifespan_context(app):
        await app.state.ingestion.wait_idle()

        async with app.state.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT count(*)
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.filename = 'iso27001-overview.en.pdf' AND c.page IS NOT NULL
                """
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] > 0, (
            "the seeded corpus must contain at least one chunk with a non-NULL page: "
            "no PDF was ingested, so the pypdf path never ran at boot"
        )

        query_vec = await embedder.embed_query("Statement of Applicability")
        hits = await app.state.store.hybrid_search(
            "Statement of Applicability", query_vec, user_id="alice", k=8
        )
        assert any(
            hit.filename == "iso27001-overview.en.pdf" and hit.page is not None for hit in hits
        ), f"expected a page-numbered hit from the PDF, got {[(h.filename, h.page) for h in hits]}"


async def test_seed_is_idempotent_across_boots(pg: object) -> None:
    counts: list[int] = []
    for _ in range(2):
        app = create_app(
            settings=make_settings(
                database_url=TEST_DATABASE_URL,
                seed_demo_data=True,
                demo_data_dir=str(DEMO_DIR),
            ),
            llm=FakeLLM(),
            embedder=FakeEmbedding(),
        )
        async with app.router.lifespan_context(app):
            await app.state.ingestion.wait_idle()
            async with app.state.pool.connection() as conn:
                cur = await conn.execute("SELECT count(*) FROM documents")
                row = await cur.fetchone()
            assert row is not None
            counts.append(int(row[0]))
    assert counts == [3, 3], f"sha256 dedup must make the seed idempotent, got {counts}"
