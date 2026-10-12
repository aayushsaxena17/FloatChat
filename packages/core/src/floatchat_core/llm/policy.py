"""Resilience and accounting around any provider (ADR-0070; PRD section 10.5).

Per call: the breaker is checked, then the daily caps (summed from the ledger), then the
attempt loop with bounded retries on retryable failures, then one ledger row. Failures become
registered error codes: ``llm_unavailable`` (503) or ``llm_budget_exhausted`` (429); the
provider's own text never reaches a user.
"""

import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from ..query.errors import QueryError
from .config import LlmSettings
from .ledger import CallRecord, Ledger, MemoryLedger, today
from .pricing import PriceTable
from .provider import (
    EmbedResult,
    EmbedTask,
    Provider,
    ProviderError,
    StructuredRequest,
    StructuredResult,
    TextRequest,
    TextStream,
    Usage,
)

log = logging.getLogger("floatchat.llm")


class CircuitBreaker:
    def __init__(self, failures: int, seconds: float, clock: Callable[[], float]) -> None:
        self.failures = failures
        self.seconds = seconds
        self.clock = clock
        self._consecutive = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if self.clock() - self._opened_at >= self.seconds:
                # Half-open: one call may try again; a failure reopens the breaker.
                self._opened_at = None
                self._consecutive = self.failures - 1
                return False
            return True

    def succeed(self) -> None:
        with self._lock:
            self._consecutive = 0
            self._opened_at = None

    def fail(self) -> None:
        with self._lock:
            self._consecutive += 1
            if self._consecutive >= self.failures:
                self._opened_at = self.clock()


class CallContext:
    """Identifiers the ledger row carries; set per message by the pipeline."""

    def __init__(
        self,
        conversation_id: str | None = None,
        message_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.correlation_id = correlation_id


class ResilientProvider:
    def __init__(
        self,
        provider: Provider,
        settings: LlmSettings,
        ledger: Ledger | None = None,
        prices: PriceTable | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.ledger: Ledger = ledger if ledger is not None else MemoryLedger()
        self.prices = prices or PriceTable()
        self.breaker = CircuitBreaker(
            settings.breaker_failures, settings.breaker_seconds, monotonic
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._clock = clock

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str:
        return self.provider.model

    @property
    def embedding_model(self) -> str:
        return self.provider.embedding_model

    # ----- guards ----------------------------------------------------------------------------

    def _check_caps(self) -> None:
        totals = self.ledger.totals(today(self._clock))
        if self.settings.daily_usd_cap and totals.usd >= self.settings.daily_usd_cap:
            raise QueryError("llm_budget_exhausted")
        if self.settings.daily_token_cap and totals.tokens >= self.settings.daily_token_cap:
            raise QueryError("llm_budget_exhausted")

    def _before(self) -> None:
        if self.breaker.open:
            raise QueryError("llm_unavailable")
        self._check_caps()

    def _record(
        self,
        feature: str,
        prompt_version: str,
        usage: Usage,
        started: float,
        status: str,
        error_code: str | None,
        context: CallContext | None,
        model: str,
        model_version: str | None = None,
    ) -> None:
        usd, flagged = self.prices.estimate(
            model, usage.input_tokens, usage.output_tokens + usage.thinking_tokens
        )
        record = CallRecord(
            feature=feature,
            provider=self.provider.name,
            model=model,
            model_version=model_version,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=usage.thinking_tokens,
            estimated_usd=usd,
            pricing_version=self.prices.version,
            priced_as_default=flagged,
            latency_ms=round((self._monotonic() - started) * 1000, 1),
            status=status,
            error_code=error_code,
            conversation_id=None if context is None else context.conversation_id,
            message_id=None if context is None else context.message_id,
            correlation_id=None if context is None else context.correlation_id,
        )
        try:
            self.ledger.record(record)
        except Exception:
            log.exception("llm ledger write failed")
        log.info(json.dumps({"event": "llm_call", **record.as_dict()}))

    def _attempts(self, call: Callable[[], Any]) -> Any:
        """Bounded retries on retryable failures; the breaker counts the final outcome."""
        delay = 0.5
        last: ProviderError | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                result = call()
            except ProviderError as error:
                last = error
                if not error.retryable or attempt == self.settings.retries:
                    break
                self._sleep(min(delay, 4.0))
                delay *= 2
                continue
            self.breaker.succeed()
            return result
        assert last is not None
        self.breaker.fail()
        raise last

    # ----- calls -----------------------------------------------------------------------------

    def structured(
        self,
        request: StructuredRequest,
        *,
        prompt_version: str,
        context: CallContext | None = None,
    ) -> StructuredResult:
        self._before()
        started = self._monotonic()
        try:
            result: StructuredResult = self._attempts(lambda: self.provider.structured(request))
        except ProviderError as error:
            self._record(
                request.purpose,
                prompt_version,
                Usage(),
                started,
                "error",
                error.kind,
                context,
                self.provider.model,
            )
            raise QueryError("llm_unavailable") from None
        self._record(
            request.purpose,
            prompt_version,
            result.usage,
            started,
            "ok",
            None,
            context,
            result.model,
            result.model_version,
        )
        return result

    def embed(
        self,
        texts: Sequence[str],
        task: EmbedTask,
        *,
        feature: str = "embed",
        context: CallContext | None = None,
    ) -> EmbedResult:
        self._before()
        started = self._monotonic()
        try:
            result: EmbedResult = self._attempts(lambda: self.provider.embed(texts, task))
        except ProviderError as error:
            self._record(
                feature,
                "embed-v1",
                Usage(),
                started,
                "error",
                error.kind,
                context,
                self.provider.embedding_model,
            )
            raise QueryError("llm_unavailable") from None
        self._record(feature, "embed-v1", result.usage, started, "ok", None, context, result.model)
        return result

    def stream_text(
        self,
        request: TextRequest,
        *,
        prompt_version: str,
        context: CallContext | None = None,
    ) -> TextStream:
        """The stream is consumed by the caller; the ledger row is written when it ends."""
        self._before()
        started = self._monotonic()
        try:
            inner: TextStream = self._attempts(lambda: self.provider.stream_text(request))
        except ProviderError as error:
            self._record(
                request.purpose,
                prompt_version,
                Usage(),
                started,
                "error",
                error.kind,
                context,
                self.provider.model,
            )
            raise QueryError("llm_unavailable") from None

        def chunks() -> Any:
            try:
                yield from inner
            except ProviderError as error:
                self.breaker.fail()
                self._record(
                    request.purpose,
                    prompt_version,
                    inner.usage,
                    started,
                    "error",
                    error.kind,
                    context,
                    inner.model,
                )
                raise QueryError("llm_unavailable") from None
            outer.set_usage(inner.usage)
            self._record(
                request.purpose,
                prompt_version,
                inner.usage,
                started,
                "ok",
                None,
                context,
                inner.model,
            )

        outer = TextStream(chunks(), inner.model)
        return outer
