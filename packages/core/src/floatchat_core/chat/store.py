"""Conversation store (ADR-0072): server-side messages scoped to a client identifier.

``PostgresStore`` writes ``app.chat_conversation`` and ``app.chat_message`` on the application
login; ``MemoryStore`` serves the tests and the harness. Results above ``RESULT_BYTES`` are not
stored; the message keeps the plan and the browser re-runs it (PRD section 14.4).
"""

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..query.errors import QueryError

CLIENT_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MESSAGE_CHARS = 2000
MESSAGES_PER_CONVERSATION = 200
CONVERSATIONS_LISTED = 200
RESULT_BYTES = 512 * 1024
TITLE_CHARS = 80


@dataclass(frozen=True)
class Conversation:
    id: str
    client_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message_count": self.message_count,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    seq: int
    role: str
    kind: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "seq": self.seq,
            "role": self.role,
            "kind": self.kind,
            "text": self.text,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "created_at": _iso(self.created_at),
        }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop a result that would exceed the stored bound; keep the plan and interpretation."""
    result = payload.get("result")
    if result is None:
        return payload
    size = len(json.dumps(result, separators=(",", ":"), default=str))
    if size <= RESULT_BYTES:
        return payload
    trimmed = dict(payload)
    trimmed.pop("result")
    trimmed["result_omitted"] = True
    trimmed["result_bytes"] = size
    return trimmed


class ConversationStore(Protocol):
    def create(self, client_id: str, title: str) -> Conversation: ...

    def get(self, client_id: str, conversation_id: str) -> Conversation | None: ...

    def rename(self, conversation_id: str, title: str) -> None: ...

    def list_for(self, client_id: str) -> list[Conversation]: ...

    def messages(self, conversation_id: str) -> list[Message]: ...

    def append(
        self,
        conversation_id: str,
        role: str,
        kind: str,
        text: str,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> Message: ...


def app_engine_from_url(url: str) -> Engine:
    """The application login (writes): a small pool, pre-ping, a 10 s statement timeout."""
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres", "postgresql+psycopg"):
        raise ValueError("postgresql URL required")
    normalized = urlunsplit(("postgresql+psycopg", parts.netloc, parts.path, parts.query, ""))
    return create_engine(
        normalized,
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=600,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=10000"},
    )


def validate_client(client_id: str | None) -> str:
    if client_id is None or not CLIENT_TOKEN.fullmatch(client_id):
        raise QueryError("client_required")
    return client_id


def validate_conversation_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError):
        raise QueryError("not_found") from None


class MemoryStore:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[Message]] = {}
        self._lock = threading.Lock()

    def create(self, client_id: str, title: str) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(str(uuid.uuid4()), client_id, title[:TITLE_CHARS], 0, now, now)
        with self._lock:
            self._conversations[conversation.id] = conversation
            self._messages[conversation.id] = []
        return conversation

    def get(self, client_id: str, conversation_id: str) -> Conversation | None:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.client_id != client_id:
            return None
        return conversation

    def rename(self, conversation_id: str, title: str) -> None:
        with self._lock:
            conversation = self._conversations[conversation_id]
            self._conversations[conversation_id] = Conversation(
                conversation.id,
                conversation.client_id,
                title[:TITLE_CHARS],
                conversation.message_count,
                conversation.created_at,
                conversation.updated_at,
            )

    def list_for(self, client_id: str) -> list[Conversation]:
        with self._lock:
            rows = [c for c in self._conversations.values() if c.client_id == client_id]
        rows.sort(key=lambda c: c.updated_at, reverse=True)
        return rows[:CONVERSATIONS_LISTED]

    def messages(self, conversation_id: str) -> list[Message]:
        with self._lock:
            return list(self._messages.get(conversation_id, []))

    def append(
        self,
        conversation_id: str,
        role: str,
        kind: str,
        text: str,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> Message:
        with self._lock:
            conversation = self._conversations[conversation_id]
            rows = self._messages[conversation_id]
            if len(rows) >= MESSAGES_PER_CONVERSATION:
                raise QueryError("chat_limit")
            message = Message(
                str(uuid.uuid4()),
                conversation_id,
                len(rows) + 1,
                role,
                kind,
                text,
                bounded_payload(payload),
                correlation_id,
            )
            rows.append(message)
            self._conversations[conversation_id] = Conversation(
                conversation.id,
                conversation.client_id,
                conversation.title,
                len(rows),
                conversation.created_at,
                datetime.now(UTC),
            )
        return message


class PostgresStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(self, client_id: str, title: str) -> Conversation:
        statement = text(
            "INSERT INTO app.chat_conversation(client_id, title) VALUES (:client_id, :title)"
            " RETURNING id, client_id, title, message_count, created_at, updated_at"
        )
        with self.engine.begin() as connection:
            row = connection.execute(
                statement, {"client_id": client_id, "title": title[:TITLE_CHARS]}
            ).one()
        return _conversation(row)

    def get(self, client_id: str, conversation_id: str) -> Conversation | None:
        statement = text(
            "SELECT id, client_id, title, message_count, created_at, updated_at"
            " FROM app.chat_conversation WHERE id = CAST(:id AS uuid) AND client_id = :client_id"
        )
        with self.engine.connect() as connection:
            row = connection.execute(
                statement, {"id": conversation_id, "client_id": client_id}
            ).one_or_none()
        return None if row is None else _conversation(row)

    def rename(self, conversation_id: str, title: str) -> None:
        statement = text(
            "UPDATE app.chat_conversation SET title = :title WHERE id = CAST(:id AS uuid)"
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"id": conversation_id, "title": title[:TITLE_CHARS]})

    def list_for(self, client_id: str) -> list[Conversation]:
        statement = text(
            "SELECT id, client_id, title, message_count, created_at, updated_at"
            " FROM app.chat_conversation WHERE client_id = :client_id"
            " ORDER BY updated_at DESC LIMIT :limit"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement, {"client_id": client_id, "limit": CONVERSATIONS_LISTED}
            ).all()
        return [_conversation(row) for row in rows]

    def messages(self, conversation_id: str) -> list[Message]:
        statement = text(
            "SELECT id, conversation_id, seq, role, kind, text, payload, correlation_id,"
            " created_at FROM app.chat_message WHERE conversation_id = CAST(:id AS uuid)"
            " ORDER BY seq"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {"id": conversation_id}).all()
        return [_message(row) for row in rows]

    def append(
        self,
        conversation_id: str,
        role: str,
        kind: str,
        text_value: str,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> Message:
        insert = text(
            "INSERT INTO app.chat_message(conversation_id, seq, role, kind, text, payload,"
            " correlation_id) SELECT CAST(:id AS uuid), coalesce(max(seq), 0) + 1, :role, :kind,"
            " :text, CAST(:payload AS jsonb), :correlation_id FROM app.chat_message"
            " WHERE conversation_id = CAST(:id AS uuid)"
            " RETURNING id, conversation_id, seq, role, kind, text, payload, correlation_id,"
            " created_at"
        )
        update = text(
            "UPDATE app.chat_conversation SET message_count = :seq, updated_at = clock_timestamp()"
            " WHERE id = CAST(:id AS uuid)"
        )
        with self.engine.begin() as connection:
            count = connection.execute(
                text(
                    "SELECT message_count FROM app.chat_conversation"
                    " WHERE id = CAST(:id AS uuid) FOR UPDATE"
                ),
                {"id": conversation_id},
            ).scalar_one_or_none()
            if count is None:
                raise QueryError("not_found")
            if int(count) >= MESSAGES_PER_CONVERSATION:
                raise QueryError("chat_limit")
            row = connection.execute(
                insert,
                {
                    "id": conversation_id,
                    "role": role,
                    "kind": kind,
                    "text": text_value,
                    "payload": json.dumps(bounded_payload(payload), default=str),
                    "correlation_id": correlation_id,
                },
            ).one()
            connection.execute(update, {"id": conversation_id, "seq": int(row.seq)})
        return _message(row)


def _conversation(row: Any) -> Conversation:
    return Conversation(
        str(row.id),
        str(row.client_id),
        str(row.title),
        int(row.message_count),
        row.created_at,
        row.updated_at,
    )


def _message(row: Any) -> Message:
    payload = row.payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Message(
        str(row.id),
        str(row.conversation_id),
        int(row.seq),
        str(row.role),
        str(row.kind),
        str(row.text),
        dict(payload or {}),
        None if row.correlation_id is None else str(row.correlation_id),
        row.created_at,
    )
