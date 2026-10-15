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
    "Indian Ocean. Tell me a period and an area, and I can compute averages, list profiles, "
    "draw T-S diagrams or find the nearest floats to a point. The named regions are the "
    "Arabian Sea, Bay of Bengal, Laccadive Sea, Andaman Sea, Indian Ocean and Southern Indian "
    "Ocean, and a bounding box or a point with a radius works too. The dashboard's coverage "
    'panel shows which months are loaded. For example, ask for "monthly mean salinity in the '
    'Bay of Bengal in February 2025 in the upper 200 dbar".'
)
REPLY_CHARS = 1200
TITLE_CHARS = 60


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
    reply: str | None = None
    title: str | None = None

    @property
    def plan_sha256(self) -> str | None:
        return None if self.plan is None else self.plan.plan_sha256

    @property
    def execution_document(self) -> dict[str, Any] | None:
        """The canonical plan without the schema label, as ``POST /v1/query`` accepts it."""
        if self.document is None or self.plan is None:
            return None
        return {key: value for key, value in self.document.items() if key != "plan_schema"}


def _title(value: Any, prompt: str) -> str | None:
    """The model's conversation title, cleaned; None keeps the first message as the title."""
    title = " ".join(str(value or "").split()).strip("\"'`“”‘’ ").rstrip(".!?;:,")
    if not title or len(title) > TITLE_CHARS or not narrate.numbers_within(title, prompt):
        return None
    return title


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
        first: bool = False,
    ) -> PlanOutcome:
        started = time.monotonic()
        timings: dict[str, float] = {}

        def step(name: str) -> None:
            if on_step is not None:
                on_step(name)

        classification = classify(question)
        timings["classify"] = round((time.monotonic() - started) * 1000, 1)
        # A model decides what every message is (ADR-0075); the rules answer greetings and help
        # only when no model can.
        if classification != "query" and self.provider.name == "offline":
            return PlanOutcome(classification, classification, timings=timings)
        try:
            return self._plan_with_model(
                question, classification, timings, started, step, context, reference_time, first
            )
        except QueryError as error:
            if classification != "query" and error.code.startswith("llm_"):
                return PlanOutcome(classification, classification, timings=timings)
            raise

    def _plan_with_model(
        self,
        question: str,
        classification: str,
        timings: dict[str, float],
        started: float,
        step: Callable[[str], None],
        context: CallContext | None,
        reference_time: str | None,
        first: bool,
    ) -> PlanOutcome:
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
                first,
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
        outcome = self._validate(result.data, classification, request.system + request.user)
        if first and isinstance(result.data, dict):
            outcome.title = _title(result.data.get("title"), request.user)
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

    def _validate(self, data: Any, classification: str, prompt: str = "") -> PlanOutcome:
        if not isinstance(data, dict):
            return PlanOutcome(
                classification,
                "clarify",
                clarification=_clarification(
                    list(ESSENTIAL_FIELDS),
                    "Sorry, I didn't follow that. Could you rephrase it with a period and an area?",
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
        if kind == "reply":
            reply = " ".join(str(data.get("reply") or "").split())[:REPLY_CHARS]
            # ADR-0073 holds for replies too: a number the model was not shown is not stated.
            if not reply or not narrate.numbers_within(reply, prompt):
                fallback = GREETING_TEXT if classification == "greeting" else HELP_TEXT
                return PlanOutcome(
                    classification,
                    "reply",
                    reply=fallback,
                    validation=[]
                    if not reply
                    else [
                        {"field": "reply", "code": "invalid_value", "message": "ungrounded number"}
                    ],
                )
            return PlanOutcome(classification, "reply", reply=reply)
        if kind == "unsupported":
            reason = str(data.get("reason") or "This request is outside what I can answer.")
            return PlanOutcome(classification, "unsupported", reason=reason[:REASON_CHARS])
        if kind != "plan":
            return PlanOutcome(
                classification,
                "clarify",
                clarification=_clarification(
                    list(ESSENTIAL_FIELDS),
                    "Sorry, I didn't follow that. Could you rephrase it with a period and an area?",
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
            question = (
                "I don't know that region. Could you name one of the listed regions, or give a "
                "bounding box or a point?"
                if error.code == "unknown_region"
                else "I couldn't turn that into a query I can run. Could you rephrase it? The "
                "interpretation below shows what didn't fit."
            )
            return PlanOutcome(
                classification,
                "clarify",
                document=document,
                clarification=_clarification(fields, question),
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
            "reply": outcome.reply,
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
        first = conversation is None
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
                first=first,
            )
        except QueryError as error:
            message = finish("error", error.text, {"code": error.code})
            yield from pending
            yield Event("error", {"code": error.code, "message": error.text})
            yield Event("message", message.as_dict())
            return
        yield from pending
        if outcome.title:
            # A summary title, as chat apps show; without a model the first message stays.
            self.store.rename(conversation.id, outcome.title)
        if outcome.kind in ("greeting", "help"):
            body = GREETING_TEXT if outcome.kind == "greeting" else HELP_TEXT
            message = finish(
                outcome.kind, body, {"interpretation": {"classification": outcome.kind}}
            )
            yield Event("message", message.as_dict())
            return
        interpretation = self._interpretation(outcome, reference)
        if outcome.kind == "reply":
            # Stored under the existing "help" kind: a conversational answer with no query.
            message = finish("help", outcome.reply or HELP_TEXT, {"interpretation": interpretation})
            yield Event("message", message.as_dict())
            return
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
                    "No committed data covers that period and area yet. The dashboard's coverage "
                    "panel shows the loaded months, so try one of those or another region."
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
