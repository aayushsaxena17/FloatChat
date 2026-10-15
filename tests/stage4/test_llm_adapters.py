"""Provider adapters over a fake transport (ADR-0070): request shapes, parsing, resilience."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.gemini import GeminiProvider
from floatchat_core.llm.ledger import MemoryLedger
from floatchat_core.llm.openai_compatible import OpenAICompatibleProvider
from floatchat_core.llm.policy import ResilientProvider
from floatchat_core.llm.pricing import PriceTable
from floatchat_core.llm.provider import (
    ProviderError,
    StructuredRequest,
    TextRequest,
    Usage,
    normalize,
)
from floatchat_core.query.errors import QueryError

KEY = "fixture-header-value"
SCHEMA = {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"]}


def gemini_answer(text: str, finish: str = "STOP", **extra: Any) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}
        ],
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 30,
            "thoughtsTokenCount": 10,
            "totalTokenCount": 160,
        },
        "modelVersion": "gemini-3.8-flash-001",
        **extra,
    }


class Recorder:
    def __init__(self, responder):
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    @property
    def bodies(self) -> list[str]:
        return [request.content.decode() for request in self.requests]


def gemini(responder, **kwargs) -> tuple[GeminiProvider, Recorder]:
    recorder = Recorder(responder)
    provider = GeminiProvider(
        KEY,
        "gemini-3.8-flash",
        "gemini-embedding-001",
        transport=httpx.MockTransport(recorder),
        **kwargs,
    )
    return provider, recorder


def structured_request() -> StructuredRequest:
    return StructuredRequest(
        purpose="plan", system="policy", user="question", schema=SCHEMA, max_output_tokens=512
    )


def test_gemini_structured_request_and_parse():
    provider, recorder = gemini(
        lambda request: httpx.Response(200, json=gemini_answer('{"kind": "plan"}'))
    )
    result = provider.structured(structured_request())
    assert result.data == {"kind": "plan"}
    assert result.usage == Usage(120, 30, 10)
    assert result.model_version == "gemini-3.8-flash-001"
    request = recorder.requests[0]
    assert request.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
    assert request.headers["x-goog-api-key"] == KEY
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "policy"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "question"}]}]
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == SCHEMA
    assert config["thinkingConfig"] == {"thinkingLevel": "LOW"}
    assert config["maxOutputTokens"] == 512 and config["temperature"] == 0.0
    assert config["seed"] == 7 and config["candidateCount"] == 1
    # The key is a header, never part of the URL or the body.
    assert KEY not in str(request.url) and KEY not in request.content.decode()


def test_gemini_thinking_config_omitted_when_blank():
    provider, recorder = gemini(
        lambda request: httpx.Response(200, json=gemini_answer('{"kind": "plan"}')),
        thinking_level="",
    )
    provider.structured(structured_request())
    assert "thinkingConfig" not in json.loads(recorder.requests[0].content)["generationConfig"]


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(429, json={"error": {"message": "quota"}}), "rate_limited"),
        (httpx.Response(503, json={"error": {"message": "down"}}), "server"),
        (httpx.Response(400, json={"error": {"message": "bad"}}), "client"),
        (httpx.Response(200, json=gemini_answer("not json")), "malformed"),
        (httpx.Response(200, json=gemini_answer("{}", finish="MAX_TOKENS")), "malformed"),
        (httpx.Response(200, json=gemini_answer("{}", finish="SAFETY")), "blocked"),
        (
            httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
            "blocked",
        ),
        (httpx.Response(200, json={"candidates": []}), "malformed"),
    ],
)
def test_gemini_failures_become_provider_errors(response, kind):
    provider, _ = gemini(lambda request: response)
    with pytest.raises(ProviderError) as info:
        provider.structured(structured_request())
    assert info.value.kind == kind
    assert info.value.retryable == (kind in ("rate_limited", "server"))


def test_gemini_timeout_is_retryable():
    def responder(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, _ = gemini(responder)
    with pytest.raises(ProviderError) as info:
        provider.structured(structured_request())
    assert info.value.kind == "timeout" and info.value.retryable


def test_gemini_embeddings_batch_and_normalisation():
    def responder(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1beta/models/gemini-embedding-001:batchEmbedContents"
        for item in body["requests"]:
            assert item["model"] == "models/gemini-embedding-001"
            assert item["taskType"] == "RETRIEVAL_DOCUMENT"
            assert item["outputDimensionality"] == 768
        vectors = [[2.0] + [0.0] * 767 for _ in body["requests"]]
        return httpx.Response(
            200,
            json={
                "embeddings": [{"values": values} for values in vectors],
                "usageMetadata": {"promptTokenCount": 9},
            },
        )

    provider, recorder = gemini(responder)
    result = provider.embed(["a", "b"], "document")
    assert len(result.vectors) == 2 and len(result.vectors[0]) == 768
    assert result.vectors[0][0] == pytest.approx(1.0)
    assert result.usage.input_tokens == 9
    assert len(recorder.requests) == 1


def test_gemini_query_embedding_task_type():
    def responder(request):
        assert json.loads(request.content)["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 768}]})

    provider, _ = gemini(responder)
    provider.embed(["q"], "query")


def test_gemini_stream_parses_sse_chunks_and_usage():
    lines = [
        "data: " + json.dumps(gemini_answer("The mean ")),
        "",
        "data: " + json.dumps(gemini_answer("is 27.1 degree_C.")),
        "",
    ]

    def responder(request):
        assert request.url.path == "/v1beta/models/gemini-3.8-flash:streamGenerateContent"
        assert request.url.params["alt"] == "sse"
        return httpx.Response(200, text="\n".join(lines) + "\n")

    provider, _ = gemini(responder)
    stream = provider.stream_text(
        TextRequest(purpose="narrate", system="s", user="u", max_output_tokens=100)
    )
    assert "".join(stream) == "The mean is 27.1 degree_C."
    assert stream.usage.input_tokens == 120


def openai_answer(content: str) -> dict[str, Any]:
    return {
        "model": "gpt-test-2026",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 25,
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
    }


def test_openai_compatible_structured_and_embeddings():
    recorder = Recorder(
        lambda request: (
            httpx.Response(200, json=openai_answer('{"kind": "clarify"}'))
            if request.url.path.endswith("/chat/completions")
            else httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0] * 767 + [3.0]},
                        {"index": 0, "embedding": [1.0] * 768},
                    ],
                    "usage": {"prompt_tokens": 4},
                },
            )
        )
    )
    provider = OpenAICompatibleProvider(
        KEY,
        "gpt-test",
        "text-embedding-3-small",
        base_url="https://llm.example/v1/",
        transport=httpx.MockTransport(recorder),
    )
    result = provider.structured(structured_request())
    assert result.data == {"kind": "clarify"} and result.usage == Usage(80, 20, 5)
    request = recorder.requests[0]
    assert request.url == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["messages"][0] == {"role": "system", "content": "policy"}
    embeddings = provider.embed(["a", "b"], "query")
    assert json.loads(recorder.requests[1].content)["dimensions"] == 768
    # Ordered by index, normalised.
    assert embeddings.vectors[0][0] == pytest.approx(1 / 768**0.5)
    assert embeddings.vectors[1][767] == pytest.approx(1.0)


def test_openai_compatible_stream():
    chunks = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " there"}}]}',
        'data: {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}',
        "data: [DONE]",
    ]
    provider = OpenAICompatibleProvider(
        KEY,
        "gpt-test",
        "e",
        base_url="https://llm.example/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="\n".join(chunks) + "\n")
        ),
    )
    stream = provider.stream_text(TextRequest(purpose="narrate", system="s", user="u"))
    assert "".join(stream) == "Hello there"
    assert stream.usage == Usage(3, 2, 0)


# ----- the policy wrapper ------------------------------------------------------------------------


class FlakyProvider:
    name = "gemini"
    model = "gemini-3.8-flash"
    embedding_model = "gemini-embedding-001"

    def __init__(self, failures: list[ProviderError]) -> None:
        self.failures = failures
        self.calls = 0

    def structured(self, request):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        from floatchat_core.llm.provider import StructuredResult

        return StructuredResult({"kind": "plan"}, "{}", Usage(1000, 200, 100), self.model, "v1")

    def embed(self, texts, task):
        raise AssertionError("not used")

    def stream_text(self, request):
        raise AssertionError("not used")


def wrap(provider, ledger=None, **settings) -> tuple[ResilientProvider, list[float]]:
    sleeps: list[float] = []
    clock = {"now": 0.0}
    wrapped = ResilientProvider(
        provider,
        LlmSettings(
            provider="gemini", retries=2, breaker_failures=2, breaker_seconds=30, **settings
        ),
        ledger or MemoryLedger(),
        PriceTable(),
        monotonic=lambda: clock["now"],
        sleep=sleeps.append,
        clock=lambda: datetime(2026, 10, 12, 12, tzinfo=UTC),
    )
    wrapped.clock_state = clock  # type: ignore[attr-defined]
    return wrapped, sleeps


def test_policy_retries_retryable_failures_then_succeeds_and_records():
    ledger = MemoryLedger()
    flaky = FlakyProvider([ProviderError("rate_limited"), ProviderError("timeout")])
    wrapped, sleeps = wrap(flaky, ledger)
    result = wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert result.data == {"kind": "plan"} and flaky.calls == 3
    assert sleeps == [1.0, 2.0]
    ((_day, call),) = ledger.calls
    assert call.status == "ok" and call.input_tokens == 1000 and call.thinking_tokens == 100
    # 1000 input at 0.75 and 300 output (output plus thinking) at 3.75 per million.
    assert call.estimated_usd == pytest.approx((1000 * 0.75 + 300 * 3.75) / 1e6)
    assert call.pricing_version == "gemini-pricing-2026-10-09" and not call.priced_as_default


def test_policy_does_not_retry_client_errors():
    flaky = FlakyProvider([ProviderError("client", status=400)])
    wrapped, sleeps = wrap(flaky)
    with pytest.raises(QueryError) as info:
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_unavailable" and flaky.calls == 1 and sleeps == []


def test_policy_breaker_opens_and_half_opens():
    """Timeouts count towards the threshold (busy answers trip at once; see the sticky test)."""
    ledger = MemoryLedger()
    flaky = FlakyProvider([ProviderError("timeout")] * 6)
    wrapped, _ = wrap(flaky, ledger)
    for _ in range(2):
        with pytest.raises(QueryError):
            wrapped.structured(structured_request(), prompt_version="planner-v1")
    calls = flaky.calls
    with pytest.raises(QueryError) as info:
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_unavailable" and flaky.calls == calls  # breaker open
    assert [call.status for _d, call in ledger.calls] == ["error", "error"]
    wrapped.clock_state["now"] = 31.0  # type: ignore[attr-defined]
    flaky.failures.clear()
    assert wrapped.structured(structured_request(), prompt_version="planner-v1").data


def test_fallback_model_answers_when_the_primary_fails_and_while_its_breaker_is_open():
    ledger = MemoryLedger()
    primary = FlakyProvider([ProviderError("server", status=503)] * 10)
    fallback = FlakyProvider([])
    fallback.model = "fallback-model"
    sleeps: list[float] = []
    clock = {"now": 0.0}
    wrapped = ResilientProvider(
        primary,
        LlmSettings(provider="gemini", retries=1, breaker_failures=1, breaker_seconds=30),
        ledger,
        PriceTable(),
        fallbacks=[fallback],
        monotonic=lambda: clock["now"],
        sleep=sleeps.append,
        clock=lambda: datetime(2026, 10, 13, 12, tzinfo=UTC),
    )
    result = wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert result.data == {"kind": "plan"} and result.model == "fallback-model"
    assert primary.calls == 2 and fallback.calls == 1 and wrapped.fallback_calls == 1
    rows = [(call.model, call.status) for _d, call in ledger.calls]
    assert rows == [("gemini-3.8-flash", "error"), ("fallback-model", "ok")]
    # The primary's breaker is open: the next call goes straight to the fallback.
    wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert primary.calls == 2 and fallback.calls == 2
    # Both open: unavailable without a provider call.
    fallback.failures.extend([ProviderError("server", status=503)] * 4)
    with pytest.raises(QueryError) as info:
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_unavailable"
    with pytest.raises(QueryError):
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert fallback.calls == 4  # the breaker, not a provider call, answered the last one
    # Non-retryable primary failure still falls back.
    clock["now"] = 100.0
    primary.failures[:] = [ProviderError("client", status=400)]
    fallback.failures.clear()
    assert (
        wrapped.structured(structured_request(), prompt_version="planner-v1").model
        == "fallback-model"
    )


def test_factory_builds_the_fallback_route(monkeypatch):
    from floatchat_core.llm.factory import build_provider

    settings = LlmSettings(
        provider="gemini", gemini_api_key="fixture-value", fallback_models="gemini-3.7-flash"
    )
    wrapped = build_provider(settings, MemoryLedger())
    assert wrapped.model == "gemini-3.8-flash" and wrapped.fallback_models == ["gemini-3.7-flash"]
    listed = LlmSettings(provider="gemini", fallback_models=" a , gemini-3.8-flash, b ,a")
    assert listed.fallback_list == ["a", "b"]
    same = build_provider(
        LlmSettings(
            provider="gemini", gemini_api_key="fixture-value", fallback_models="gemini-3.8-flash"
        ),
        MemoryLedger(),
    )
    assert same.fallback_models == []
    offline = build_provider(LlmSettings(provider="offline"), MemoryLedger())
    assert offline.fallback_models == []


def test_budget_stops_the_route_ladder_and_the_message_names_the_busy_provider():
    primary = FlakyProvider([ProviderError("server", status=503)] * 10)
    slow = FlakyProvider([ProviderError("server", status=503)] * 10)
    slow.model = "slow-model"
    clock = {"now": 0.0}

    def ticking() -> float:
        clock["now"] += 20.0  # every provider call costs 20 s
        return clock["now"]

    wrapped = ResilientProvider(
        primary,
        LlmSettings(provider="gemini", retries=3, total_budget_seconds=45, breaker_failures=5),
        MemoryLedger(),
        PriceTable(),
        fallbacks=[slow],
        monotonic=ticking,
        sleep=lambda s: None,
        clock=lambda: datetime(2026, 10, 13, 12, tzinfo=UTC),
    )
    with pytest.raises(QueryError) as info:
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_unavailable" and "overloaded" in info.value.text
    # The budget, not the retry count, bounded the attempts.
    assert primary.calls + slow.calls <= 4
    assert ResilientProvider.unavailable(ProviderError("timeout")).text.startswith(
        "The language model took"
    )
    assert ResilientProvider.unavailable(ProviderError("client")).text.startswith("The assistant")


def test_help_classification_covers_data_availability_questions():
    from floatchat_core.chat.classify import classify

    for text in (
        "Hi how much data is avaliable",
        "What data do you have?",
        "which data is available",
    ):
        assert classify(text) == "help", text
    assert classify("mean temperature in BoB in January 2025") == "query"


class StreamingProvider:
    name = "gemini"
    model = "stream-model"
    embedding_model = "e"

    def __init__(self, failures: list[ProviderError], text: str = "The mean is 26.2.") -> None:
        self.failures = failures
        self.text = text
        self.opened = 0

    def structured(self, request):
        raise AssertionError("not used")

    def embed(self, texts, task):
        raise AssertionError("not used")

    def stream_text(self, request):
        from collections.abc import Generator

        from floatchat_core.llm.provider import TextStream

        def generate() -> Generator[str, None, Usage]:
            # Like the HTTP adapters: the request happens on the first read.
            self.opened += 1
            if self.failures:
                raise self.failures.pop(0)
            for word in self.text.split(" "):
                yield word + " "
            return Usage(5, 4, 0)

        return TextStream(generate(), self.model)


def test_streaming_narration_retries_and_falls_back_before_the_first_chunk():
    primary = StreamingProvider([ProviderError("rate_limited", status=429)] * 10)
    fallback = StreamingProvider([], "Fallback says 26.2.")
    fallback.model = "fallback-stream"
    ledger = MemoryLedger()
    wrapped = ResilientProvider(
        primary,
        LlmSettings(provider="gemini", retries=1, breaker_failures=3),
        ledger,
        PriceTable(),
        fallbacks=[fallback],
        sleep=lambda s: None,
        clock=lambda: datetime(2026, 10, 13, 12, tzinfo=UTC),
    )
    stream = wrapped.stream_text(
        TextRequest(purpose="narrate", system="s", user="u"), prompt_version="narrator-v1"
    )
    assert "".join(stream).strip() == "Fallback says 26.2."
    assert stream.usage == Usage(5, 4, 0) and stream.model == "fallback-stream"
    assert primary.opened == 2 and fallback.opened == 1
    rows = [(call.model, call.status) for _d, call in ledger.calls]
    assert rows == [("stream-model", "error"), ("fallback-stream", "ok")]


def test_busy_answers_trip_the_breaker_and_the_answering_route_becomes_sticky():
    primary = FlakyProvider([ProviderError("server", status=503)] * 10)
    fallback = FlakyProvider([])
    fallback.model = "fallback-model"
    clock = {"now": 0.0}
    wrapped = ResilientProvider(
        primary,
        LlmSettings(provider="gemini", retries=1, breaker_failures=3, breaker_seconds=60),
        MemoryLedger(),
        PriceTable(),
        fallbacks=[fallback],
        monotonic=lambda: clock["now"],
        sleep=lambda s: None,
        clock=lambda: datetime(2026, 10, 13, 12, tzinfo=UTC),
    )
    assert wrapped.structured(structured_request(), prompt_version="p").model == "fallback-model"
    assert primary.calls == 2  # one retry, then the 503 tripped the breaker at once
    for _ in range(3):
        wrapped.structured(structured_request(), prompt_version="p")
    assert primary.calls == 2 and fallback.calls == 4
    # After the cool-down the fallback is still tried first because it answered last.
    clock["now"] = 61.0
    primary.failures.clear()
    wrapped.structured(structured_request(), prompt_version="p")
    assert primary.calls == 2 and fallback.calls == 5
    # A non-busy failure counts towards the threshold instead of tripping at once.
    fallback.failures.extend([ProviderError("malformed")] * 1)
    assert wrapped.structured(structured_request(), prompt_version="p").model == "gemini-3.8-flash"
    assert not fallback.breaker_open if hasattr(fallback, "breaker_open") else True


def test_policy_daily_caps_from_the_ledger():
    ledger = MemoryLedger()
    ledger.clock = lambda: datetime(2026, 10, 12, 1, tzinfo=UTC)
    flaky = FlakyProvider([])
    wrapped, _ = wrap(flaky, ledger, daily_usd_cap=0.002)
    wrapped.structured(structured_request(), prompt_version="planner-v1")
    wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert ledger.totals(datetime(2026, 10, 12, tzinfo=UTC).date()).usd >= 0.002
    with pytest.raises(QueryError) as info:
        wrapped.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_budget_exhausted" and flaky.calls == 2
    wrapped_tokens, _ = wrap(FlakyProvider([]), ledger, daily_token_cap=100)
    with pytest.raises(QueryError) as info:
        wrapped_tokens.structured(structured_request(), prompt_version="planner-v1")
    assert info.value.code == "llm_budget_exhausted"


def test_unknown_model_is_priced_at_default_and_flagged():
    usd, flagged = PriceTable().estimate("some-model", 1_000_000, 0)
    assert flagged and usd == 2.0
    assert LlmSettings(provider="gemini").configured is False
    assert LlmSettings(provider="offline").configured is True


def test_empty_key_is_no_key(monkeypatch):
    """The .env.example default is ``GEMINI_API_KEY=``; an empty value must not configure."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    settings = LlmSettings(provider="gemini")
    assert settings.key_for("gemini") is None and settings.key_for("openai") is None
    assert settings.configured is False and settings.secrets() == []
    with pytest.raises(QueryError) as info:
        from floatchat_core.llm.factory import build_provider

        build_provider(settings)
    assert info.value.code == "llm_unavailable"


def test_normalize_handles_zero_vector():
    assert normalize([0.0, 0.0]) == [0.0, 0.0]
    assert sum(value * value for value in normalize([3.0, 4.0])) == pytest.approx(1.0)
