"""The chat flow (PRD section 9.2; ADR-0072, ADR-0073) as a generator of events.

``ChatService.plan`` runs classify -> retrieve -> plan -> validate and is what the benchmark
harness measures; ``ChatService.respond`` adds the store, execution, sanitisation and narration
and yields the events the API streams (plan section 5). The model's output is untrusted:
``validate_plan`` and the region fixture decide, and a failing plan becomes a clarification.
"""

import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..llm.policy import CallContext, ResilientProvider
from ..llm.provider import StructuredRequest, TextRequest, Usage
from ..query.errors import QueryError
from ..query.geography import resolve_geography
from ..query.limits import QueryLimits
from ..query.plan import QueryPlan, validate_plan
from ..rag.corpus import CONTEXT_TYPES, catalogue_summary
from ..rag.retriever import Hit, Retriever
from . import narrate
from .classify import GREETING_TEXT, classify
from .prompts import (
    NARRATOR_POLICY,
    NARRATOR_VERSION,
    PLANNER_VERSION,
    narrator_user,
    planner_system,
    planner_user,
)
from .schema import ESSENTIAL_FIELDS, PLANNER_SCHEMA, to_plan_document
from .store import MESSAGE_CHARS, ConversationStore, Message

log = logging.getLogger("floatchat.chat")
Mode = Literal["schema_only", "rag", "rag_examples"]
EXAMPLES_TOP_K = 5
REASON_CHARS = 300
QUESTION_CHARS = 300
HELP_TEXT = (
    "I answer questions about Argo temperature, salinity and pressure observations in the "
    "Indian Ocean. Give a period and an area, for example 'monthly mean salinity in the Bay of "
    "Bengal in February 2025 in the upper 200 dbar', 'list the 20 newest profiles in the "
    "Arabian Sea in March 2025', 'T-S diagram for the Laccadive Sea in January 2025' or "
    "'the 5 nearest floats to 15N 65E in January 2025'. Regions: Arabian Sea, Bay of Bengal, "
    "Laccadive Sea, Andaman Sea, Indian Ocean, Southern Indian Ocean; or give a bounding box or "
    "a point with a radius. The local dataset covers the Indian Ocean for the months the "
    "dashboard's coverage panel lists (January to March 2025 on the development stack). "
    "Exports, forecasts and biogeochemical variables arrive in later stages."
)


class QueryEngine(Protocol):
    def parameters(self) -> dict[str, Any]: ...

    def query(self, payload: Any) -> dict[str, Any]: ...

    def environment_info(self) -> dict[str, Any]: ...


@dataclass
class Event:
    type: str
    data: dict[str, Any]


@dataclass
class PlanOutcome:
    classification: str
    kind: str
    plan: QueryPlan | None = None
    document: dict[str, Any] | None = None
    clarification: dict[str, Any] | None = None
    reason: str | None = None
    validation: list[dict[str, str]] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    examples: list[Hit] = field(default_factory=list)
    usage: Usage = Usage()
    latency_ms: float = 0.0
    model: str = ""
    model_version: str | None = None
    raw: Any = None
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def plan_sha256(self) -> str | None:
        return None if self.plan is None else self.plan.plan_sha256

    @property
    def execution_document(self) -> dict[str, Any] | None:
        """The canonical plan without the schema label, as ``POST /v1/query`` accepts it."""
        if self.document is None or self.plan is None:
            return None
        return {key: value for key, value in self.document.items() if key != "plan_schema"}


def _clarification(missing: list[str], question: str) -> dict[str, Any]:
    return {"missing": missing, "question": question[:QUESTION_CHARS]}


class ChatService:
    def __init__(
        self,
        engine: QueryEngine,
        provider: ResilientProvider,
        retriever: Retriever | None,
        store: ConversationStore,
        *,
        limits: QueryLimits | None = None,
        mode: Mode = "rag_examples",
        narrate_with_model: bool = True,
        retrieval_top_k: int = 12,
        planner_max_output_tokens: int = 4096,
        narrator_max_output_tokens: int = 400,
    ) -> None:
        self.engine = engine
        self.provider = provider
        self.retriever = retriever
        self.store = store
        self.limits = limits or QueryLimits()
        self.mode = mode
        self.narrate_with_model = narrate_with_model
        self.retrieval_top_k = retrieval_top_k
        self.planner_max_output_tokens = planner_max_output_tokens
        self.narrator_max_output_tokens = narrator_max_output_tokens
        self._summary = catalogue_summary(self.limits)
        self._system = planner_system(self._summary, PLANNER_SCHEMA)

    # ----- planning (shared with the harness) --------------------------------------------------

    def _environment(self) -> tuple[str, str]:
        try:
            environment = self.engine.environment_info()
        except QueryError:
            environment = {}
        reference = environment.get("reference_time") or "unknown"
        window = environment.get("postgresql_window") or {}
        window_text = (
            f"{window.get('start')} to {window.get('end')}" if window.get("start") else "unknown"
        )
        return str(reference), window_text

    def retrieve(self, question: str) -> tuple[list[Hit], list[Hit]]:
        if self.mode == "schema_only" or self.retriever is None:
            return [], []
        vector = self.provider.embed([question], "query", feature="plan").vectors[0]
        hits = self.retriever.search(vector, top_k=self.retrieval_top_k, doc_types=CONTEXT_TYPES)
        examples: list[Hit] = []
        if self.mode == "rag_examples":
            examples = self.retriever.search(vector, top_k=EXAMPLES_TOP_K, doc_types=["example"])
        return hits, examples

    def plan(
        self,
        question: str,
        *,
        context: CallContext | None = None,
        on_step: Callable[[str], None] | None = None,
        reference_time: str | None = None,
    ) -> PlanOutcome:
        started = time.monotonic()
        timings: dict[str, float] = {}

        def step(name: str) -> None:
            if on_step is not None:
                on_step(name)

        classification = classify(question)
        timings["classify"] = round((time.monotonic() - started) * 1000, 1)
        if classification != "query":
            return PlanOutcome(classification, classification, timings=timings)
        step("retrieve")
        mark = time.monotonic()
        hits, examples = self.retrieve(question)
        timings["retrieve"] = round((time.monotonic() - mark) * 1000, 1)
        step("plan")
        mark = time.monotonic()
        reference, window = self._environment()
        if reference_time is not None:
            reference = reference_time
        request = StructuredRequest(
            purpose="plan",
            system=self._system,
            user=planner_user(
                question,
                reference,
                window,
                [hit.document for hit in hits],
                [hit.document for hit in examples],
            ),
            schema=PLANNER_SCHEMA,
            max_output_tokens=self.planner_max_output_tokens,
            context={
                "question": question,
                "reference_time": reference,
                "regions": [
                    record["name"]
                    for record in self.engine.parameters()["geography"]["named_region"]
                ],
                "documents": [hit.document.as_dict() for hit in hits],
                "time_span_days": self.limits.time_span_days,
            },
        )
        result = self.provider.structured(request, prompt_version=PLANNER_VERSION, context=context)
        timings["plan"] = round((time.monotonic() - mark) * 1000, 1)
        step("validate")
        mark = time.monotonic()
        outcome = self._validate(result.data, classification)
        outcome.hits, outcome.examples = hits, examples
        outcome.usage, outcome.model, outcome.model_version = (
            result.usage,
            result.model,
            result.model_version,
        )
        outcome.raw = result.data
        timings["validate"] = round((time.monotonic() - mark) * 1000, 1)
        outcome.timings = timings
        outcome.latency_ms = round((time.monotonic() - started) * 1000, 1)
        return outcome

    def _validate(self, data: Any, classification: str) -> PlanOutcome:
        if not isinstance(data, dict):
            return PlanOutcome(
                classification,
                "clarify",
                clarification=_clarification(
                    list(ESSENTIAL_FIELDS), "I could not understand the request; please restate it."
                ),
                validation=[{"field": "plan", "code": "invalid_value", "message": "not an object"}],
            )
        kind = data.get("kind")
        if kind == "clarify":
            clarification = data.get("clarification") or {}
            missing = [
                str(item) for item in (clarification.get("missing") or []) if isinstance(item, str)
            ][:7]
            question = str(clarification.get("question") or "Could you give the missing details?")
            return PlanOutcome(
                classification,
                "clarify",
                clarification=_clarification(missing or list(ESSENTIAL_FIELDS), question),
            )
        if kind == "unsupported":
            reason = str(data.get("reason") or "This request is outside what I can answer.")
            return PlanOutcome(classification, "unsupported", reason=reason[:REASON_CHARS])
        if kind != "plan":
            return PlanOutcome(
                classification,
                "clarify",
                clarification=_clarification(
                    list(ESSENTIAL_FIELDS), "I could not form a request; please restate it."
                ),
                validation=[{"field": "kind", "code": "invalid_value", "message": "unknown kind"}],
            )
        document = to_plan_document(data.get("plan"))
        try:
            plan = validate_plan(document, self.limits)
            resolve_geography(plan.geography)
        except QueryError as error:
            details = [detail.as_dict() for detail in error.details]
            if error.code == "unknown_region":
                details = [{"field": "geography", "code": "unknown_region", "message": error.text}]
            fields = sorted({detail["field"].split(".")[0] for detail in details}) or ["plan"]
            text = "; ".join(f"{d['field']}: {d['message']}" for d in details[:5])
            return PlanOutcome(
                classification,
                "clarify",
                document=document,
                clarification=_clarification(
                    fields, f"I could not form a valid request ({text}). Could you restate it?"
                ),
                validation=details,
            )
        return PlanOutcome(classification, "plan", plan=plan, document=plan.canonical())

    # ----- the conversation ----------------------------------------------------------------------

    def _interpretation(self, outcome: PlanOutcome, reference: str) -> dict[str, Any]:
        return {
            "classification": outcome.classification,
            "kind": outcome.kind,
            "provider": self.provider.name,
            "model": outcome.model or self.provider.model,
            "model_version": outcome.model_version,
            "prompt_version": PLANNER_VERSION,
            "narrator_version": NARRATOR_VERSION,
            "embedding_model": self.provider.embedding_model,
            "retrieval_mode": self.mode,
            "retrieved": [hit.as_dict() for hit in outcome.hits],
            "examples": [hit.as_dict() for hit in outcome.examples],
            "reference_time": reference,
            "plan": outcome.document,
            "plan_sha256": outcome.plan_sha256,
            "clarification": outcome.clarification,
            "reason": outcome.reason,
            "validation": outcome.validation,
            "timings": dict(outcome.timings),
            "tokens": {
                "input": outcome.usage.input_tokens,
                "output": outcome.usage.output_tokens,
                "thinking": outcome.usage.thinking_tokens,
            },
        }

    def _narrate(
        self,
        question: str,
        response: dict[str, Any],
        context: CallContext,
        interpretation: dict[str, Any],
    ) -> Iterator[Event]:
        """Yields token events and finally sets ``interpretation['narrative']``."""
        summary = narrate.summarize(response)
        fallback = narrate.template(summary)
        interpretation["narrative_source"] = "template"
        interpretation["narrative_rejected"] = False
        if not self.narrate_with_model or self.provider.name == "offline":
            for chunk in _chunks(fallback):
                yield Event("token", {"text": chunk})
            interpretation["narrative"] = fallback
            return
        mark = time.monotonic()
        try:
            stream = self.provider.stream_text(
                TextRequest(
                    purpose="narrate",
                    system=NARRATOR_POLICY,
                    user=narrator_user(question, summary),
                    max_output_tokens=self.narrator_max_output_tokens,
                    context={"template": fallback},
                ),
                prompt_version=NARRATOR_VERSION,
                context=context,
            )
            text = ""
            for chunk in stream:
                text += chunk
                yield Event("token", {"text": chunk})
            usage = stream.usage
        except QueryError as error:
            interpretation["narration_error"] = error.code
            interpretation["narrative"] = fallback
            return
        interpretation["timings"]["narrate"] = round((time.monotonic() - mark) * 1000, 1)
        interpretation["tokens"]["narrate_input"] = usage.input_tokens
        interpretation["tokens"]["narrate_output"] = usage.output_tokens + usage.thinking_tokens
        text = text.strip()
        if text and narrate.grounded(text, summary):
            interpretation["narrative_source"] = "model"
            interpretation["narrative"] = text
        else:
            interpretation["narrative_rejected"] = bool(text)
            interpretation["narrative"] = fallback

    def respond(
        self,
        *,
        client_id: str,
        conversation_id: str | None,
        text: str,
        correlation_id: str | None = None,
    ) -> Iterator[Event]:
        text = text.strip()
        if not text or len(text) > MESSAGE_CHARS:
            raise QueryError("chat_limit")
        conversation = None
        if conversation_id is not None:
            conversation = self.store.get(client_id, conversation_id)
            if conversation is None:
                raise QueryError("not_found")
        if conversation is None:
            conversation = self.store.create(client_id, text)
        user_message = self.store.append(conversation.id, "user", "user", text, {}, correlation_id)
        context = CallContext(conversation.id, user_message.id, correlation_id)
        yield Event(
            "conversation",
            {"conversation_id": conversation.id, "user_message": user_message.as_dict()},
        )
        reference, _window = self._environment()

        def finish(kind: str, body: str, payload: dict[str, Any]) -> Message:
            return self.store.append(
                conversation.id, "assistant", kind, body, payload, correlation_id
            )

        yield Event("status", {"step": "classify"})
        pending: list[Event] = []
        try:
            outcome = self.plan(
                text,
                context=context,
                on_step=lambda step: pending.append(Event("status", {"step": step})),
            )
        except QueryError as error:
            message = finish("error", error.text, {"code": error.code})
            yield from pending
            yield Event("error", {"code": error.code, "message": error.text})
            yield Event("message", message.as_dict())
            return
        yield from pending
        if outcome.kind in ("greeting", "help"):
            body = GREETING_TEXT if outcome.kind == "greeting" else HELP_TEXT
            message = finish(
                outcome.kind, body, {"interpretation": {"classification": outcome.kind}}
            )
            yield Event("message", message.as_dict())
            return
        interpretation = self._interpretation(outcome, reference)
        if outcome.kind == "clarify":
            assert outcome.clarification is not None
            message = finish(
                "clarification",
                outcome.clarification["question"],
                {"interpretation": interpretation, "clarification": outcome.clarification},
            )
            yield Event("interpretation", interpretation)
            yield Event("message", message.as_dict())
            return
        if outcome.kind == "unsupported":
            message = finish(
                "unsupported", outcome.reason or "", {"interpretation": interpretation}
            )
            yield Event("interpretation", interpretation)
            yield Event("message", message.as_dict())
            return
        assert outcome.document is not None
        yield Event("status", {"step": "execute"})
        mark = time.monotonic()
        try:
            response = self.engine.query(outcome.execution_document)
        except QueryError as error:
            interpretation["timings"]["execute"] = round((time.monotonic() - mark) * 1000, 1)
            interpretation["execution_error"] = error.code
            if error.code == "coverage_missing":
                body = (
                    "No committed data covers that period and area yet. Try the January to "
                    "March 2025 window or another region."
                )
                message = finish(
                    "answer", body, {"interpretation": interpretation, "plan": outcome.document}
                )
                yield Event("interpretation", interpretation)
                yield Event("message", message.as_dict())
                return
            message = finish(
                "error", error.text, {"interpretation": interpretation, "code": error.code}
            )
            yield Event("interpretation", interpretation)
            yield Event("error", {"code": error.code, "message": error.text})
            yield Event("message", message.as_dict())
            return
        interpretation["timings"]["execute"] = round((time.monotonic() - mark) * 1000, 1)
        interpretation["execution"] = response.get("execution")
        interpretation["transformation"] = (response.get("interpretation") or {}).get(
            "transformation"
        )
        interpretation["engine_interpretation"] = response.get("interpretation")
        yield Event("status", {"step": "sanitise"})
        yield Event("interpretation", interpretation)
        yield Event("result", response)
        yield Event("status", {"step": "narrate"})
        yield from self._narrate(text, response, context, interpretation)
        message = finish(
            "answer",
            str(interpretation.get("narrative", "")),
            {"interpretation": interpretation, "plan": outcome.document, "result": response},
        )
        log.info(
            json.dumps(
                {
                    "event": "chat_answer",
                    "conversation_id": conversation.id,
                    "message_id": message.id,
                    "plan_sha256": outcome.plan_sha256,
                    "model": interpretation["model"],
                    "prompt_version": PLANNER_VERSION,
                    "retrieved": [hit.document.identifier for hit in outcome.hits],
                    "narrative_source": interpretation.get("narrative_source"),
                }
            )
        )
        yield Event("message", message.as_dict())


def _chunks(text: str, size: int = 6) -> Iterator[str]:
    words = text.split(" ")
    for index in range(0, len(words), size):
        yield (" " if index else "") + " ".join(words[index : index + size])
