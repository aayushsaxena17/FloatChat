"""Stage 4 over the disposable PostGIS server (ADR-0071, ADR-0072): migration 0018, the pgvector
retriever against the in-memory ranking, the conversation store and the call ledger.

Lives beside the Stage 2 database fixture it reuses (``tests/stage2/conftest.py``).
"""

from datetime import UTC, datetime

import pytest
from floatchat_core.chat.store import PostgresStore, app_engine_from_url
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.ledger import CallRecord, MemoryLedger, PostgresLedger
from floatchat_core.llm.offline import OfflineProvider
from floatchat_core.llm.policy import ResilientProvider
from floatchat_core.query.catalogue import engine_from_url
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.rag.corpus import CONTEXT_TYPES, build_corpus
from floatchat_core.rag.embeddings import hash_embed, hash_embed_many
from floatchat_core.rag.retriever import MemoryRetriever, PgVectorRetriever
from sqlalchemy.exc import DBAPIError

from scripts.semantic_seed import seed

pytestmark = pytest.mark.integration

QUESTIONS = [
    "monthly mean temperature off Oman in Q1 2025 in the upper 100 dbar",
    "salinity in BoB last month regardless of QC",
    "nearest floats to 15N 65E",
    "T-S diagram for the Laccadive Sea",
    "how many measurements were taken",
]


def admin_url(database) -> str:
    return f"postgresql://postgres@127.0.0.1:{database.port}/postgres"


@pytest.mark.usefixtures("allow_loopback")
def test_seed_retrieve_store_and_ledger(database):
    admin = app_engine_from_url(admin_url(database))
    provider = ResilientProvider(OfflineProvider(), LlmSettings(provider="offline"), MemoryLedger())
    documents = build_corpus()
    first = seed(admin, provider, documents)
    assert first["embedded"] == len(documents) and first["retired"] == 0
    second = seed(admin, provider, documents)
    assert second["embedded"] == 0 and second["unchanged"] == len(documents)
    # The query login reads the table; the ranking equals the in-memory retriever's.
    query_engine = engine_from_url(database.query_url, QueryLimits())
    pg = PgVectorRetriever(query_engine, provider.embedding_model)
    memory = MemoryRetriever(
        documents, hash_embed_many([d.embedding_text for d in documents]), provider.embedding_model
    )
    for question in QUESTIONS:
        vector = hash_embed(question)
        expected = memory.search(vector, top_k=8, doc_types=CONTEXT_TYPES)
        actual = pg.search(vector, top_k=8, doc_types=CONTEXT_TYPES)
        assert [hit.document.identifier for hit in actual] == [
            hit.document.identifier for hit in expected
        ], question
        for mine, theirs in zip(actual, expected, strict=True):
            assert mine.score == pytest.approx(theirs.score, abs=1e-6)
        examples = pg.search(vector, top_k=3, doc_types=["example"])
        assert all(hit.document.doc_type == "example" for hit in examples)
    # A changed document is re-embedded; a removed one is retired and no longer retrieved.
    changed = list(documents)
    changed[0] = type(changed[0])(
        changed[0].doc_type, changed[0].key, changed[0].title, changed[0].text + " changed", {}
    )
    third = seed(admin, provider, changed[:-1])
    assert third["embedded"] == 1 and third["retired"] == 1
    retired = documents[-1].identifier
    hits = pg.search(hash_embed(documents[-1].embedding_text), top_k=50)
    assert retired not in {hit.document.identifier for hit in hits}
    # The query login cannot write.
    with pytest.raises(DBAPIError):
        with query_engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM app.semantic_document")
    # Conversations and messages on the application side (the admin stands in for it here).
    store = PostgresStore(admin)
    conversation = store.create("client-a", "first question")
    assert store.get("client-a", conversation.id) is not None
    assert store.get("client-b", conversation.id) is None
    user = store.append(conversation.id, "user", "user", "hello", {}, "corr-1")
    answer = store.append(
        conversation.id,
        "assistant",
        "answer",
        "hi",
        {"plan": {"a": 1}, "result": {"rows": []}},
        "corr-1",
    )
    assert (user.seq, answer.seq) == (1, 2)
    rows = store.messages(conversation.id)
    assert [row.kind for row in rows] == ["user", "answer"]
    assert rows[1].payload["plan"] == {"a": 1} and rows[1].correlation_id == "corr-1"
    listed = store.list_for("client-a")
    assert listed[0].id == conversation.id and listed[0].message_count == 2
    assert store.list_for("client-b") == []
    with pytest.raises(QueryError):
        store.append("00000000-0000-4000-8000-000000000999", "user", "user", "x", {}, None)
    # The ledger sums the UTC day.
    ledger = PostgresLedger(admin)
    ledger.record(
        CallRecord(
            "plan",
            "gemini",
            "gemini-3.8-flash",
            "planner-v1",
            1000,
            200,
            50,
            0.0017,
            "gemini-pricing-2026-10-09",
            False,
            123.4,
            "ok",
            None,
            "v1",
            conversation.id,
            answer.id,
            "corr-1",
        )
    )
    totals = ledger.totals(datetime.now(UTC).date())
    assert totals.calls == 1 and totals.tokens == 1250 and totals.usd == pytest.approx(0.0017)
