"""The LLM call ledger (ADR-0070): one row per call; the daily caps are sums over it."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class CallRecord:
    feature: str
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_usd: float
    pricing_version: str
    priced_as_default: bool
    latency_ms: float
    status: str
    error_code: str | None = None
    model_version: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    correlation_id: str | None = None

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thinking_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "estimated_usd": self.estimated_usd,
            "pricing_version": self.pricing_version,
            "priced_as_default": self.priced_as_default,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_code": self.error_code,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class DailyTotals:
    usd: float
    tokens: int
    calls: int


class Ledger(Protocol):
    def record(self, call: CallRecord) -> None: ...

    def totals(self, day: date) -> DailyTotals: ...


def today(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> date:
    return clock().astimezone(UTC).date()


class MemoryLedger:
    """Process-local ledger for tests and the harness."""

    def __init__(self) -> None:
        self.calls: list[tuple[date, CallRecord]] = []
        self._lock = threading.Lock()
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def record(self, call: CallRecord) -> None:
        with self._lock:
            self.calls.append((today(self.clock), call))

    def totals(self, day: date) -> DailyTotals:
        with self._lock:
            rows = [call for when, call in self.calls if when == day]
        return DailyTotals(
            round(sum(call.estimated_usd for call in rows), 6),
            sum(call.tokens for call in rows),
            len(rows),
        )


class PostgresLedger:
    """``app.llm_call`` on the application role; one short autocommit statement per call."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(self, call: CallRecord) -> None:
        statement = text(
            "INSERT INTO app.llm_call(feature, provider, model, model_version, prompt_version,"
            " input_tokens, output_tokens, thinking_tokens, estimated_usd, pricing_version,"
            " priced_as_default, latency_ms, status, error_code, conversation_id, message_id,"
            " correlation_id) VALUES (:feature, :provider, :model, :model_version,"
            " :prompt_version, :input_tokens, :output_tokens, :thinking_tokens, :estimated_usd,"
            " :pricing_version, :priced_as_default, :latency_ms, :status, :error_code,"
            " CAST(:conversation_id AS uuid), CAST(:message_id AS uuid), :correlation_id)"
        )
        with self.engine.begin() as connection:
            connection.execute(statement, call.as_dict())

    def totals(self, day: date) -> DailyTotals:
        statement = text(
            "SELECT coalesce(sum(estimated_usd), 0), coalesce(sum(input_tokens + output_tokens"
            " + thinking_tokens), 0), count(*) FROM app.llm_call WHERE day = :day"
        )
        with self.engine.connect() as connection:
            usd, tokens, calls = connection.execute(statement, {"day": day}).one()
        return DailyTotals(float(usd), int(tokens), int(calls))
