"""Two retrievers, one ranking (ADR-0071): cosine similarity, exact scan, filtered by model.

``MemoryRetriever`` serves the harness and the unit tests without a database;
``PgVectorRetriever`` serves the API over ``app.semantic_document``. Both order by score
descending, then document type and key, so the same corpus gives the same context.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .corpus import Document
from .embeddings import cosine


@dataclass(frozen=True)
class Hit:
    document: Document
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.document.identifier,
            "doc_type": self.document.doc_type,
            "title": self.document.title,
            "score": round(self.score, 4),
        }


class Retriever(Protocol):
    embedding_model: str

    def search(
        self, vector: Sequence[float], *, top_k: int, doc_types: Sequence[str] | None = None
    ) -> list[Hit]: ...


def _ordered(hits: list[Hit], top_k: int) -> list[Hit]:
    hits.sort(key=lambda hit: (-round(hit.score, 9), hit.document.doc_type, hit.document.key))
    return hits[:top_k]


class MemoryRetriever:
    def __init__(
        self,
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
        embedding_model: str,
    ) -> None:
        if len(documents) != len(vectors):
            raise ValueError("one vector per document")
        self.documents = list(documents)
        self.vectors = [list(vector) for vector in vectors]
        self.embedding_model = embedding_model

    def search(
        self, vector: Sequence[float], *, top_k: int, doc_types: Sequence[str] | None = None
    ) -> list[Hit]:
        wanted = None if doc_types is None else set(doc_types)
        hits = [
            Hit(document, cosine(vector, stored))
            for document, stored in zip(self.documents, self.vectors, strict=True)
            if wanted is None or document.doc_type in wanted
        ]
        return _ordered(hits, top_k)


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class PgVectorRetriever:
    """Exact cosine scan on pgvector; the query login reads the table (migration 0018)."""

    def __init__(self, engine: Engine, embedding_model: str) -> None:
        self.engine = engine
        self.embedding_model = embedding_model

    def search(
        self, vector: Sequence[float], *, top_k: int, doc_types: Sequence[str] | None = None
    ) -> list[Hit]:
        statement = text(
            "SELECT doc_type, key, title, text, metadata,"
            " 1 - (embedding <=> CAST(:vector AS vector)) AS score"
            " FROM app.semantic_document"
            " WHERE embedding_model = :model AND access_scope = 'public'"
            " AND (valid_to IS NULL OR valid_to > clock_timestamp())"
            " AND (:all_types OR doc_type = ANY(CAST(:types AS text[])))"
            " ORDER BY embedding <=> CAST(:vector AS vector), doc_type, key"
            " LIMIT :limit"
        )
        parameters = {
            "vector": vector_literal(vector),
            "model": self.embedding_model,
            "all_types": doc_types is None,
            "types": list(doc_types or []),
            "limit": int(top_k),
        }
        with self.engine.connect() as connection:
            rows = connection.execute(statement, parameters).mappings().all()
        hits = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            document = Document(
                row["doc_type"], row["key"], row["title"], row["text"], dict(metadata or {})
            )
            hits.append(Hit(document, float(row["score"])))
        return _ordered(hits, top_k)
