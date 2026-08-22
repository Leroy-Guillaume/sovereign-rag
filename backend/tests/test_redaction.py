"""PII redaction: pattern engine, LLM boundary decorator, end-to-end masking."""

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings
from sovereign_rag.llm.base import ChatMessage, LLMClient, collect
from sovereign_rag.llm.redacting import RedactingLLMClient
from sovereign_rag.redaction import redact_patterns
from sovereign_rag.store.base import ChunkIn

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag_test"
)

AUTH_ALICE = {"Authorization": "Bearer test-key-alice"}


# --- pattern engine ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Contact jean.dupont+legal@example.ch svp", "Contact [email redacted] svp"),
        ("IBAN CH93 0076 2011 6238 5295 7 pour le loyer", "IBAN [iban redacted] 7 pour le loyer"),
        ("AVS 756.1234.5678.97 du dossier", "AVS [avs redacted] du dossier"),
        ("Appelez le +41 79 123 45 67 demain", "Appelez le [phone redacted] demain"),
        ("Bureau: 022 546 76 00 (Geneve)", "Bureau: [phone redacted] (Geneve)"),
        ("Tel 0033 6 12 34 56 78 direct", "Tel [phone redacted] direct"),
    ],
)
def test_patterns_mask_direct_identifiers(text: str, expected: str) -> None:
    assert redact_patterns(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Legal citations and bench numbers must NEVER be touched.
        "l'art. 8 al. 1 nLPD et l'art. 24 s'appliquent",
        "Article 32(1)(a) of Regulation (EU) 2016/679",
        "MRR 0.775 sur 159 questions, hit@8 96 %",
        "le 21.08.2026 a 14h30",
        "ISO/IEC 27001:2022 annexe A.5.28",
        "publie au JO L 119 du 4.5.2016, p. 1-88",
    ],
)
def test_patterns_leave_legal_text_alone(text: str) -> None:
    assert redact_patterns(text) == text


# --- boundary decorator ------------------------------------------------------


async def test_decorator_masks_every_outbound_role() -> None:
    inner = FakeLLM(chunks=["ok"])
    wrapped = RedactingLLMClient(cast(LLMClient, inner), redact_patterns)
    messages = [
        ChatMessage(role="system", content="Context: mail jean@ex.ch"),
        ChatMessage(role="user", content="Son numero est +41 79 123 45 67 ?"),
        ChatMessage(role="assistant", content="IBAN CH93 0076 2011 6238 5295 deja cite"),
    ]
    text, prompt_tokens, _ = await collect(wrapped.stream_chat(messages))
    assert text == "ok"
    assert prompt_tokens == 10  # chunks pass through untouched
    sent = [m.content for m in inner.last_messages]
    assert sent[0] == "Context: mail [email redacted]"
    assert sent[1] == "Son numero est [phone redacted] ?"
    assert "[iban redacted]" in sent[2]
    assert wrapped.model == inner.model
    await wrapped.healthcheck()


# --- end to end: provider sees masked text, the user does not ----------------


async def test_chat_masks_outbound_but_not_user_facing_sources(
    api_client: ClientFactory, pg: Any
) -> None:
    embedder = FakeEmbedding()
    store = InMemoryVectorStore()
    content = "Le DPO est joignable sur dpo@example.ch pour toute question nLPD."
    embeddings = await embedder.embed_documents([content])
    await store.add_chunks(
        uuid4(), [ChunkIn(chunk_index=0, content=content, embedding=embeddings[0])]
    )
    llm = FakeLLM(chunks=["Reponse [1]."])
    settings = make_settings(database_url=TEST_DATABASE_URL, redaction_provider="patterns")
    async with api_client(settings=settings, llm=llm, embedder=embedder, store=store) as client:
        resp = await client.post(
            "/api/chat",
            json={"conversation_id": None, "message": "Ecrire a jean@prive.ch au sujet du DPO ?"},
            headers=AUTH_ALICE,
        )
        assert resp.status_code == 200
        raw = resp.text
    # Outbound to the provider: both the passage's email and the one typed by
    # the user are masked, system prompt and user turn alike.
    outbound = "\n".join(m.content for m in llm.last_messages)
    assert "dpo@example.ch" not in outbound
    assert "jean@prive.ch" not in outbound
    assert outbound.count("[email redacted]") >= 2
    # User-facing sources stay verbatim: they never leave the infrastructure.
    assert "dpo@example.ch" in raw


# --- ner provider (needs the pii extra; CI installs all extras) --------------


def test_ner_provider_matches_the_measured_configuration() -> None:
    pytest.importorskip("presidio_analyzer")
    from sovereign_rag.redaction import create_redactor

    redact = create_redactor("ner")
    # Names on top of the direct identifiers, in all three languages. The
    # exact span can swallow the French particle ("de Jean Dupont"), so the
    # assertions check what matters: the name is gone, the mask is there.
    masked = redact("Dossier de Jean Dupont, contact jean.dupont@example.ch")
    assert "Jean Dupont" not in masked
    assert "[name redacted]" in masked
    assert "[email redacted]" in masked
    assert "[name redacted]" in redact("Die Meldung von Hans Mueller wurde registriert.")
    assert "[name redacted]" in redact("The officer Mary Brown signed the notification.")
    # Clean legal text stays untouched: the 2 % false-positive budget is the
    # whole point of PERSON-only.
    legal = "Le responsable du traitement doit annoncer au PFPDT selon l'art. 24 nLPD."
    assert redact(legal) == legal


def test_guess_language() -> None:
    from sovereign_rag.redaction import guess_language

    assert (
        guess_language("Le responsable du traitement doit assurer la protection des donnees")
        == "fr"
    )
    assert (
        guess_language("Der Verantwortliche muss die Datensicherheit mit dem Gesetz beachten")
        == "de"
    )
    assert guess_language("The controller shall ensure the security of the processing") == "en"
