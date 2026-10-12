"""Embed the semantic corpus and upsert it into ``app.semantic_document`` (ADR-0071).

    uv run --all-packages --frozen python -m scripts.semantic_seed            # from the environment
    LLM_PROVIDER=offline python -m scripts.semantic_seed --database-url ...   # explicit

Reads ``LLM_*`` and the provider key from the environment, ``DATABASE_URL`` (the application
login) unless ``--database-url`` is given. Only documents whose content hash changed, or that
the active embedding model has not seen, are embedded; removed documents are retired by
setting ``valid_to``. Prints one JSON line with the counts. The API image ships this file.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from floatchat_core.chat.store import app_engine_from_url
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.factory import build_provider
from floatchat_core.llm.policy import ResilientProvider
from floatchat_core.query.errors import QueryError
from floatchat_core.rag.corpus import Document, build_corpus
from floatchat_core.rag.retriever import vector_literal
from sqlalchemy import text
from sqlalchemy.engine import Engine

EMBED_BATCH = 50


def existing_hashes(engine: Engine, embedding_model: str) -> dict[str, str]:
    statement = text(
        "SELECT doc_type || ':' || key AS id, content_sha256 FROM app.semantic_document"
        " WHERE embedding_model = :model AND valid_to IS NULL"
    )
    with engine.connect() as connection:
        rows = connection.execute(statement, {"model": embedding_model}).all()
    return {str(row.id): str(row.content_sha256) for row in rows}


def upsert(
    engine: Engine,
    documents: Sequence[Document],
    vectors: Sequence[Sequence[float]],
    embedding_model: str,
    embedding_version: str,
) -> None:
    statement = text(
        "INSERT INTO app.semantic_document(doc_type, key, title, text, metadata, content_sha256,"
        " embedding_model, embedding_version, embedding_dimensions, embedding, valid_from,"
        " valid_to, updated_at) VALUES (:doc_type, :key, :title, :text, CAST(:metadata AS jsonb),"
        " :content_sha256, :embedding_model, :embedding_version, 768, CAST(:embedding AS vector),"
        " clock_timestamp(), NULL, clock_timestamp())"
        " ON CONFLICT (doc_type, key, embedding_model) DO UPDATE SET title = EXCLUDED.title,"
        " text = EXCLUDED.text, metadata = EXCLUDED.metadata,"
        " content_sha256 = EXCLUDED.content_sha256, embedding_version = EXCLUDED.embedding_version,"
        " embedding = EXCLUDED.embedding, valid_from = clock_timestamp(), valid_to = NULL,"
        " updated_at = clock_timestamp()"
    )
    rows = [
        {
            "doc_type": document.doc_type,
            "key": document.key,
            "title": document.title,
            "text": document.text,
            "metadata": json.dumps(document.metadata, sort_keys=True, default=str),
            "content_sha256": document.content_sha256,
            "embedding_model": embedding_model,
            "embedding_version": embedding_version,
            "embedding": vector_literal(vector),
        }
        for document, vector in zip(documents, vectors, strict=True)
    ]
    if rows:
        with engine.begin() as connection:
            connection.execute(statement, rows)


def retire(engine: Engine, embedding_model: str, keep: Sequence[str]) -> int:
    statement = text(
        "UPDATE app.semantic_document SET valid_to = clock_timestamp(), updated_at ="
        " clock_timestamp() WHERE embedding_model = :model AND valid_to IS NULL"
        " AND NOT (doc_type || ':' || key = ANY(CAST(:keep AS text[])))"
    )
    with engine.begin() as connection:
        return int(
            connection.execute(statement, {"model": embedding_model, "keep": list(keep)}).rowcount
        )


def seed(
    engine: Engine, provider: ResilientProvider, documents: Sequence[Document] | None = None
) -> dict[str, Any]:
    documents = list(build_corpus() if documents is None else documents)
    model = provider.embedding_model
    present = existing_hashes(engine, model)
    changed = [
        document
        for document in documents
        if present.get(document.identifier) != document.content_sha256
    ]
    embedded = 0
    for start in range(0, len(changed), EMBED_BATCH):
        batch = changed[start : start + EMBED_BATCH]
        result = provider.embed([document.embedding_text for document in batch], "document")
        upsert(engine, batch, result.vectors, model, result.model)
        embedded += len(batch)
    retired = retire(engine, model, [document.identifier for document in documents])
    return {
        "event": "semantic_seed",
        "embedding_model": model,
        "documents": len(documents),
        "embedded": embedded,
        "unchanged": len(documents) - embedded,
        "retired": retired,
        "at": datetime.now(UTC).isoformat(),
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    arguments = parser.parse_args(argv)
    if not arguments.database_url:
        print("DATABASE_URL (the application login) is required", file=sys.stderr)
        return 2
    settings = LlmSettings()
    if not settings.configured:
        print(
            json.dumps(
                {
                    "event": "semantic_seed",
                    "skipped": "llm_unavailable",
                    "provider": settings.provider,
                }
            )
        )
        return 0
    try:
        provider = build_provider(settings)
        record = seed(app_engine_from_url(arguments.database_url), provider)
    except QueryError as error:
        # An unusable provider or budget is a skip, never a failed start-up (PRD section 22).
        print(
            json.dumps(
                {"event": "semantic_seed", "skipped": error.code, "provider": settings.provider}
            )
        )
        return 0
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
