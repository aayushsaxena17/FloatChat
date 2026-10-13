"""Resilience and accounting around any provider (ADR-0070; PRD section 10.5).

Per call: the breaker is checked, then the daily caps (summed from the ledger), then the
attempt loop with bounded retries on retryable failures, then one ledger row. A configured
fallback model has its own breaker: when the primary fails after its retries, or while its
breaker is open, the fallback answers (first live runs on 2026-10-13 saw whole Flash models
answer 503 "high demand" for minutes). Failures become registered error codes:
``llm_unavailable`` (503) or ``llm_budget_exhausted`` (429); the provider's own text never
reaches a user, but the status and kind reach the operator log.
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

    def trip(self) -> None:
        """Open at once: a busy answer (429 or 503) means the model is not worth asking again
        within the cool-down, whatever the consecutive-failure threshold says."""
        with self._lock:
            self._consecutive = self.failures
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


class _Route:
    """A provider with its breaker; the primary and the fallback are two routes."""

    def __init__(self, provider: Provider, breaker: CircuitBreaker, role: str) -> None:
        self.provider = provider
        self.breaker = breaker
        self.role = role


class ResilientProvider:
    def __init__(
        self,
        provider: Provider,
        settings: LlmSettings,
        ledger: Ledger | None = None,
        prices: PriceTable | None = None,
        *,
        fallbacks: Sequence[Provider] = (),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.ledger: Ledger = ledger if ledger is not None else MemoryLedger()
        self.prices = prices or PriceTable()
        self._monotonic = monotonic
        self._sleep = sleep
        self._clock = clock
        self.breaker = CircuitBreaker(
            settings.breaker_failures, settings.breaker_seconds, monotonic
        )
        self.primary = _Route(provider, self.breaker, "primary")
        self.fallbacks = [
            _Route(
                candidate,
                CircuitBreaker(settings.breaker_failures, settings.breaker_seconds, monotonic),
                "fallback",
            )
            for candidate in fallbacks
        ]
        self.fallback_calls = 0
        self._preferred: _Route | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str:
        return self.provider.model

    @property
    def fallback_models(self) -> list[str]:
        return [route.provider.model for route in self.fallbacks]

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

    def _routes(self) -> list[_Route]:
        """The routes to try in order; a route with an open breaker is skipped.

        The route that answered last goes first ("sticky"): once the primary has shown itself
        busy, the next call starts where the last one succeeded instead of walking the ladder
        again (each rung costs seconds on an overloaded provider).
        """
        routes = [self.primary, *self.fallbacks]
        if self._preferred is not None and self._preferred in routes:
            routes.remove(self._preferred)
            routes.insert(0, self._preferred)
        usable = [route for route in routes if not route.breaker.open]
        if not usable:
            raise QueryError("llm_unavailable")
        return usable

    def _before(self) -> list[_Route]:
        routes = self._routes()
        self._check_caps()
        return routes

    def _record(
        self,
        feature: str,
        prompt_version: str,
        usage: Usage,
        started: float,
        status: str,
        error: ProviderError | None,
        context: CallContext | None,
        model: str,
        model_version: str | None = None,
        route: str = "primary",
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
            error_code=None if error is None else error.kind,
            conversation_id=None if context is None else context.conversation_id,
            message_id=None if context is None else context.message_id,
            correlation_id=None if context is None else context.correlation_id,
        )
        try:
            self.ledger.record(record)
        except Exception:
            log.exception("llm ledger write failed")
        detail: dict[str, Any] = {"route": route}
        if error is not None:
            # The provider's status and our own classification; never its message text.
            detail["error_status"] = error.status
        log.info(json.dumps({"event": "llm_call", **record.as_dict(), **detail}, default=str))

    def _attempts(
        self, route: _Route, call: Callable[[Provider], Any], deadline: float | None = None
    ) -> Any:
        """Bounded retries on retryable failures; the route's breaker counts the outcome."""
        delay = 1.0
        last: ProviderError | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                result = call(route.provider)
            except ProviderError as error:
                last = error
                exhausted = deadline is not None and self._monotonic() >= deadline
                if not error.retryable or attempt == self.settings.retries or exhausted:
                    break
                self._sleep(min(delay, 8.0))
                delay *= 2
                continue
            route.breaker.succeed()
            self._preferred = route
            return result
        assert last is not None
        if last.kind in ("rate_limited", "server"):
            route.breaker.trip()
        else:
            route.breaker.fail()
        if self._preferred is route:
            self._preferred = None
        raise last

    @staticmethod
    def unavailable(error: ProviderError | None) -> QueryError:
        """The user-visible ``llm_unavailable`` with a fixed message for the failure class."""
        kind = None if error is None else error.kind
        if kind in ("rate_limited", "server"):
            message = (
                "The language model is overloaded at the moment. Give it a minute and try "
                "again. The dashboard and map keep working in the meantime."
            )
        elif kind == "timeout":
            message = "The language model took too long to answer. Please try again."
        elif kind == "blocked":
            message = "The language model declined this request. Could you rephrase it?"
        else:
            return QueryError("llm_unavailable")
        return QueryError("llm_unavailable", message=message)

    def _with_fallback(
        self,
        routes: Sequence[_Route],
        call: Callable[[Provider], Any],
        on_failure: Callable[[_Route, ProviderError], None],
    ) -> tuple[Any, _Route]:
        """Try each usable route in order within the whole-call budget; a route's final
        failure is recorded before the next route is tried."""
        deadline = self._monotonic() + self.settings.total_budget_seconds
        last: ProviderError | None = None
        for route in routes:
            if last is not None and self._monotonic() >= deadline:
                break
            try:
                return self._attempts(route, call, deadline), route
            except ProviderError as error:
                last = error
                on_failure(route, error)
                if route.role == "primary" and len(routes) > 1:
                    log.warning(
                        json.dumps(
                            {
                                "event": "llm_fallback",
                                "primary": route.provider.model,
                                "error": error.kind,
                                "status": error.status,
                            }
                        )
                    )
        assert last is not None
        raise last

    # ----- calls -----------------------------------------------------------------------------

    def structured(
        self,
        request: StructuredRequest,
        *,
        prompt_version: str,
        context: CallContext | None = None,
    ) -> StructuredResult:
        routes = self._before()
        started = self._monotonic()

        def failed(route: _Route, error: ProviderError) -> None:
            self._record(
                request.purpose,
                prompt_version,
                Usage(),
                started,
                "error",
                error,
                context,
                route.provider.model,
                route=route.role,
            )

        try:
            answer, route = self._with_fallback(
                routes, lambda provider: provider.structured(request), failed
            )
        except ProviderError as error:
            raise self.unavailable(error) from None
        result: StructuredResult = answer
        if route.role == "fallback":
            self.fallback_calls += 1
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
            route=route.role,
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
        # Embeddings use one model; the fallback route is for generation only.
        self._before()
        if self.primary.breaker.open:
            raise QueryError("llm_unavailable")
        started = self._monotonic()
        try:
            result: EmbedResult = self._attempts(
                self.primary, lambda provider: provider.embed(texts, task)
            )
        except ProviderError as error:
            self._record(
                feature,
                "embed-v1",
                Usage(),
                started,
                "error",
                error,
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
        routes = self._before()
        started = self._monotonic()

        def failed(route: _Route, error: ProviderError) -> None:
            self._record(
                request.purpose,
                prompt_version,
                Usage(),
                started,
                "error",
                error,
                context,
                route.provider.model,
                route=route.role,
            )

        def open_stream(provider: Provider) -> tuple[TextStream, Any, str | None]:
            # Adapters open the HTTP stream on the first read; priming it here puts the
            # request inside the retry and fallback logic instead of the consumer's loop.
            stream = provider.stream_text(request)
            iterator = iter(stream)
            try:
                head: str | None = next(iterator)
            except StopIteration:
                head = None
            return stream, iterator, head

        try:
            opened, route = self._with_fallback(routes, open_stream, failed)
        except ProviderError as error:
            raise self.unavailable(error) from None
        inner: TextStream = opened[0]
        rest: Any = opened[1]
        head: str | None = opened[2]
        if route.role == "fallback":
            self.fallback_calls += 1

        def chunks() -> Any:
            try:
                if head is not None:
                    yield head
                yield from rest
            except ProviderError as error:
                route.breaker.fail()
                self._record(
                    request.purpose,
                    prompt_version,
                    inner.usage,
                    started,
                    "error",
                    error,
                    context,
                    inner.model,
                    route=route.role,
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
                route=route.role,
            )

        outer = TextStream(chunks(), inner.model)
        return outer
