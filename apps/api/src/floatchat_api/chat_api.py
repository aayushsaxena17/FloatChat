"""Stage 4 chat endpoints (PRD section 13; ADR-0072).

``POST /v1/chat/messages`` answers JSON or, when the request accepts ``text/event-stream``,
streams the pipeline's events (plan section 5). Conversations are scoped to the opaque
``X-FloatChat-Client`` identifier. The conversation store needs only the database; the planner
needs the configured provider, so history stays readable while the model is unavailable
(PRD section 22).
"""

import json
import logging
from collections.abc import Callable, Iterator
from queue import Queue
from threading import Lock, Thread
from typing import Any

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import StreamingResponse
from floatchat_core.chat.pipeline import ChatService, Event
from floatchat_core.chat.store import (
    ConversationStore,
    PostgresStore,
    app_engine_from_url,
    validate_client,
    validate_conversation_id,
)
from floatchat_core.config import Settings
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.factory import build_provider
from floatchat_core.llm.ledger import PostgresLedger
from floatchat_core.query.errors import QueryError
from floatchat_core.rag.retriever import PgVectorRetriever
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from floatchat_api.query_api import ERRORS, QueryRuntime, correlation_id

log = logging.getLogger("floatchat.api.chat")
CLIENT_HEADER = "X-FloatChat-Client"


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


class ChatMessage(_Loose):
    id: str
    conversation_id: str
    seq: int
    role: str
    kind: str
    text: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    created_at: str


class ChatConversation(_Loose):
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ChatAnswer(_Loose):
    conversation_id: str
    message: ChatMessage


class ConversationList(_Loose):
    conversations: list[ChatConversation]


class ConversationDetail(_Loose):
    conversation: ChatConversation
    messages: list[ChatMessage]


class ChatRuntime:
    """Builds the store on first use and the planner on first chat; nothing at import time."""

    def __init__(
        self,
        query_runtime: QueryRuntime,
        settings_factory: Callable[[], Settings] = Settings,
        llm_settings_factory: Callable[[], LlmSettings] = LlmSettings,
        service: ChatService | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self.query_runtime = query_runtime
        self.settings_factory = settings_factory
        self.llm_settings_factory = llm_settings_factory
        self._service = service
        self._store = store
        self._lock = Lock()

    def store(self) -> ConversationStore:
        with self._lock:
            if self._store is None:
                try:
                    settings = self.settings_factory()
                except Exception:
                    raise QueryError("service_unavailable") from None
                self._store = PostgresStore(
                    app_engine_from_url(settings.database_url.get_secret_value())
                )
            return self._store

    def service(self) -> ChatService:
        with self._lock:
            if self._service is None:
                self._service = self._build()
            return self._service

    def _build(self) -> ChatService:
        try:
            llm = self.llm_settings_factory()
        except Exception:
            raise QueryError("llm_unavailable") from None
        if not llm.configured:
            raise QueryError("llm_unavailable")
        try:
            settings = self.settings_factory()
        except Exception:
            raise QueryError("service_unavailable") from None
        engine = app_engine_from_url(settings.database_url.get_secret_value())
        if self._store is None:
            self._store = PostgresStore(engine)
        provider = build_provider(llm, PostgresLedger(engine))
        query_service = self.query_runtime.service()
        retriever = PgVectorRetriever(query_service.catalogue.engine, provider.embedding_model)
        return ChatService(
            query_service,
            provider,
            retriever,
            self._store,
            limits=self.query_runtime.limits,
            retrieval_top_k=llm.retrieval_top_k,
            planner_max_output_tokens=llm.planner_max_output_tokens,
            narrator_max_output_tokens=llm.narrator_max_output_tokens,
        )


def sse(event: Event) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"


def detached_stream(events: Iterator[Event], identifier: str) -> Iterator[str]:
    """Run the pipeline to completion on a worker thread; yield its events as they arrive.

    Closing the returned generator (a client disconnect) never stops the worker, so the
    assistant message is stored whether or not anyone is still listening.
    """
    pending: Queue[Event | None] = Queue()

    def work() -> None:
        try:
            for event in events:
                pending.put(event)
        except QueryError as error:
            pending.put(Event("error", {"code": error.code, "message": error.text}))
        except Exception:
            log.exception("chat pipeline failed %s", identifier)
            failure = QueryError("internal_error")
            pending.put(Event("error", {"code": failure.code, "message": failure.text}))
        finally:
            pending.put(None)

    Thread(target=work, name="floatchat-chat", daemon=True).start()
    while True:
        event = pending.get()
        if event is None:
            return
        yield sse(event)


def install_chat(app: FastAPI, runtime: ChatRuntime) -> None:
    router = APIRouter(prefix="/v1/chat", responses=ERRORS)

    def _client(value: str | None) -> str:
        return validate_client(value)

    @router.post("/messages", response_model=ChatAnswer, response_model_exclude_unset=True)
    async def post_message(
        request: Request,
        body: ChatMessageRequest,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = _client(x_floatchat_client)
        conversation = (
            None if body.conversation_id is None else validate_conversation_id(body.conversation_id)
        )
        identifier = getattr(request.state, "correlation_id", None) or correlation_id(request)
        # The planner (and its provider) is built here, so a missing key answers
        # llm_unavailable before any message is stored.
        service = await run_in_threadpool(runtime.service)
        events = service.respond(
            client_id=client,
            conversation_id=conversation,
            text=body.text,
            correlation_id=identifier,
        )
        if "text/event-stream" in request.headers.get("accept", ""):
            # The pipeline runs in its own thread and stores every message it produces; the
            # stream only observes it. A browser that reloads mid-answer closes the stream,
            # and the answer is still there when the conversation is fetched again.
            return StreamingResponse(
                iterate_in_threadpool(detached_stream(events, identifier)),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        def collect() -> dict[str, Any]:
            conversation_id = conversation
            message = None
            failure: QueryError | None = None
            for event in events:
                if event.type == "conversation":
                    conversation_id = event.data["conversation_id"]
                elif event.type == "error":
                    failure = QueryError(event.data["code"])
                elif event.type == "message":
                    message = event.data
            if failure is not None:
                raise failure
            assert message is not None and conversation_id is not None
            return {"conversation_id": conversation_id, "message": message}

        return await run_in_threadpool(collect)

    @router.get(
        "/conversations", response_model=ConversationList, response_model_exclude_unset=True
    )
    async def list_conversations(
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = _client(x_floatchat_client)
        store = await run_in_threadpool(runtime.store)
        rows = await run_in_threadpool(store.list_for, client)
        return {"conversations": [row.as_dict() for row in rows]}

    @router.get(
        "/conversations/{conversation_id}",
        response_model=ConversationDetail,
        response_model_exclude_unset=True,
    )
    async def conversation_detail(
        conversation_id: str,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = _client(x_floatchat_client)
        identifier = validate_conversation_id(conversation_id)
        store = await run_in_threadpool(runtime.store)
        conversation = await run_in_threadpool(store.get, client, identifier)
        if conversation is None:
            raise QueryError("not_found")
        messages = await run_in_threadpool(store.messages, identifier)
        return {
            "conversation": conversation.as_dict(),
            "messages": [message.as_dict() for message in messages],
        }

    app.include_router(router)
