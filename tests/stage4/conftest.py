"""Stage 4 fixtures: sockets denied, the engine double, the offline chat service."""

import socket
import sys
from pathlib import Path

import pytest
from floatchat_core.chat.pipeline import ChatService
from floatchat_core.chat.store import MemoryStore
from floatchat_core.rag.corpus import build_corpus
from floatchat_core.rag.embeddings import hash_embed_many
from floatchat_core.rag.retriever import MemoryRetriever

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doubles import EngineDouble, offline_provider  # noqa: E402


@pytest.fixture(autouse=True)
def deny_sockets(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Stage 4 tests deny all Python socket connections")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture(autouse=True)
def no_llm_keys(monkeypatch):
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "LLM_GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def corpus():
    documents = build_corpus()
    vectors = hash_embed_many([document.embedding_text for document in documents])
    return documents, vectors


@pytest.fixture
def retriever(corpus):
    documents, vectors = corpus
    return MemoryRetriever(documents, vectors, "hash-embed-v1")


@pytest.fixture
def engine():
    return EngineDouble()


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def service(engine, retriever, store):
    return ChatService(engine, offline_provider(), retriever, store)
