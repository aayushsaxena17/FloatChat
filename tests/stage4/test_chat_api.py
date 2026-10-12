"""Chat endpoints over doubles (ADR-0072) and the PRD section 22 degradation (ADR-0069)."""

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from floatchat_api.main import create_app
from floatchat_core.chat.store import MemoryStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2"))
from test_api import FakeService  # noqa: E402  (the Stage 2 query-service double)

HEADER = "X-FloatChat-Client"
QUESTION = "monthly mean temperature in the Arabian Sea in Q1 2025 in the upper 100 dbar"


@pytest.fixture
def client(service, store):
    app = create_app(query_service=FakeService(), chat_service=service, chat_store=store)
    with TestClient(app) as test_client:
        yield test_client


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        kind = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((kind, json.loads(data)))
    return events


def test_client_header_is_required(client):
    response = client.post("/v1/chat/messages", json={"text": "hi"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "client_required"
    response = client.get("/v1/chat/conversations", headers={HEADER: "bad header!"})
    assert response.status_code == 400


def test_json_answer_and_history(client):
    headers = {HEADER: "browser-1", "X-Correlation-ID": "chat-1"}
    response = client.post("/v1/chat/messages", json={"text": QUESTION}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    message = body["message"]
    assert message["kind"] == "answer" and message["role"] == "assistant"
    assert message["payload"]["interpretation"]["provider"] == "offline"
    assert message["payload"]["result"]["result"]["row_count"] == 3
    assert response.headers["X-Correlation-ID"] == "chat-1"
    conversation_id = body["conversation_id"]
    listed = client.get("/v1/chat/conversations", headers=headers).json()["conversations"]
    assert [row["id"] for row in listed] == [conversation_id]
    assert listed[0]["message_count"] == 2 and listed[0]["title"].startswith("monthly mean")
    detail = client.get(f"/v1/chat/conversations/{conversation_id}", headers=headers).json()
    assert [row["kind"] for row in detail["messages"]] == ["user", "answer"]
    # Another client sees nothing of it.
    other = {HEADER: "browser-2"}
    assert client.get("/v1/chat/conversations", headers=other).json()["conversations"] == []
    assert client.get(f"/v1/chat/conversations/{conversation_id}", headers=other).status_code == 404
    assert client.get("/v1/chat/conversations/not-a-uuid", headers=headers).status_code == 404
    # A follow-up in the same conversation.
    follow = client.post(
        "/v1/chat/messages",
        json={"text": "hello", "conversation_id": conversation_id},
        headers=headers,
    )
    assert follow.json()["message"]["seq"] == 4


def test_sse_stream_event_order(client):
    headers = {HEADER: "browser-1", "Accept": "text/event-stream"}
    with client.stream(
        "POST", "/v1/chat/messages", json={"text": QUESTION}, headers=headers
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.read().decode())
    types = [kind for kind, _ in events]
    assert types[0] == "conversation" and types[-1] == "message"
    assert "interpretation" in types and "result" in types and "token" in types
    steps = [data["step"] for kind, data in events if kind == "status"]
    assert steps[:3] == ["classify", "retrieve", "plan"]
    final = events[-1][1]
    assert (
        final["kind"] == "answer"
        and final["payload"]["plan"]["geography"]["value"] == "Arabian Sea"
    )


def test_clarification_and_unsupported_over_json(client):
    headers = {HEADER: "browser-1"}
    response = client.post(
        "/v1/chat/messages", json={"text": "temperature in BoB"}, headers=headers
    )
    assert response.json()["message"]["kind"] == "clarification"
    response = client.post(
        "/v1/chat/messages", json={"text": "oxygen in BoB in March 2025"}, headers=headers
    )
    assert response.json()["message"]["kind"] == "unsupported"


def test_request_validation(client):
    headers = {HEADER: "browser-1"}
    assert client.post("/v1/chat/messages", json={"text": ""}, headers=headers).status_code == 400
    assert client.post("/v1/chat/messages", json={"txt": "x"}, headers=headers).status_code == 400
    assert (
        client.post("/v1/chat/messages", json={"text": "x" * 2001}, headers=headers).status_code
        == 400
    )


def test_llm_unavailable_leaves_the_rest_of_the_api_working(monkeypatch):
    """PRD section 22: no key, the chat answers 503 and everything else is unaffected."""
    assert "GEMINI_API_KEY" not in os.environ
    monkeypatch.setenv("GEMINI_API_KEY", "")  # the .env.example default
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    store = MemoryStore()
    app = create_app(query_service=FakeService(), chat_store=store)
    with TestClient(app) as client:
        headers = {HEADER: "browser-1"}
        response = client.post("/v1/chat/messages", json={"text": QUESTION}, headers=headers)
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "llm_unavailable" and "dashboard" in body["message"]
        # Nothing was stored for a message that could not be planned.
        assert client.get("/v1/chat/conversations", headers=headers).json()["conversations"] == []
        assert client.get("/v1/health/live").status_code == 200
        assert client.get("/v1/catalog/parameters").status_code == 200
        assert client.get("/v1/profiles").status_code == 200
        query = client.post(
            "/v1/query",
            json={
                "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
                "geography": {"kind": "named_region", "value": "Arabian Sea"},
                "variables": ["temperature"],
                "operation": {"kind": "profiles", "limit": 10},
            },
        )
        assert query.status_code == 200


def test_openapi_documents_the_chat_routes(client):
    schema = client.get("/openapi.json").json()
    assert "/v1/chat/messages" in schema["paths"]
    assert "/v1/chat/conversations/{conversation_id}" in schema["paths"]
    assert schema["info"]["version"] == "0.3.0"
