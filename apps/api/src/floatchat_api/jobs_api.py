"""Stage 5 job endpoints (PRD section 13; ADR-0079, ADR-0081).

``POST /v1/exports`` creates (or attaches to) an export job and answers 202; the job routes
are scoped to the ``X-FloatChat-Client`` identifier; ``GET /v1/jobs/{id}/events`` streams the
job's progress events as SSE with ``id:`` lines and ``Last-Event-ID`` resume; artefacts are
downloaded through the API with a short-lived signed token (the browser never reaches the
object store).
"""

import logging
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any

import boto3
from botocore.config import Config
from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import StreamingResponse
from floatchat_core.chat.store import app_engine_from_url, validate_client
from floatchat_core.config import Settings
from floatchat_core.jobs.artefacts import download_path, sign, verify
from floatchat_core.jobs.model import (
    TERMINAL_STATES,
    Artefact,
    JobLimits,
    parse_export_request,
    plan_for,
)
from floatchat_core.jobs.store import JobStore, PostgresJobStore, validate_job_id
from floatchat_core.query.errors import QueryError
from floatchat_core.query.geography import resolve_geography
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from floatchat_api.query_api import ERRORS, correlation_id

log = logging.getLogger("floatchat.api.jobs")
CLIENT_HEADER = "X-FloatChat-Client"
IDEMPOTENCY_HEADER = "Idempotency-Key"
HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 1.0
STREAM_SECONDS = 6 * 3600
CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "parquet": "application/octet-stream",
    "json": "application/json",
}
JOB_ERRORS: dict[int | str, dict[str, Any]] = {
    **ERRORS,
    403: ERRORS[404],
    409: ERRORS[404],
    410: ERRORS[404],
}


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExportRequestBody(BaseModel):
    """``export-request-v1`` (ADR-0081); the plan fields without an operation."""

    model_config = ConfigDict(extra="forbid")
    time_range: dict[str, Any]
    geography: dict[str, Any]
    depth_dbar: dict[str, Any] | None = None
    variables: list[str] | None = None
    qc_policy: str | None = None
    format: str = Field(default="parquet", pattern="^(csv|parquet)$")
    idempotency_key: str | None = Field(default=None, max_length=128)


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int | None = Field(default=None, ge=1)


class JobRecord(_Loose):
    id: str
    kind: str
    queue: str
    state: str
    idempotency_key: str | None = None
    request: dict[str, Any]
    request_sha256: str
    plan: dict[str, Any]
    progress: dict[str, Any]
    result: dict[str, Any]
    error: dict[str, Any] | None = None
    version: int
    attempts: int
    cancel_requested_at: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class JobChunkRecord(_Loose):
    id: str
    seq: int
    kind: str
    label: str
    interval: dict[str, Any] | None = None
    tiles: list[dict[str, Any]]
    state: str
    attempts: int
    ingestion_run_id: str | None = None
    evidence: dict[str, Any]
    error: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ArtefactRecord(_Loose):
    id: str
    format: str
    role: str
    filename: str
    bytes: int
    sha256: str
    row_count: int
    profile_count: int
    manifest: dict[str, Any]
    state: str
    created_at: str
    expires_at: str
    download_url: str | None = None


class JobCreated(_Loose):
    job: JobRecord
    created: bool
    attached: bool


class JobList(_Loose):
    jobs: list[JobRecord]


class JobDetail(_Loose):
    job: JobRecord
    chunks: list[JobChunkRecord]
    artefacts: list[ArtefactRecord]


class JobEnvelope(_Loose):
    job: JobRecord


class JobsRuntime:
    """The store and the signing key, built on first use; nothing at import time."""

    def __init__(
        self,
        settings_factory: Callable[[], Settings] = Settings,
        store: JobStore | None = None,
        limits: JobLimits | None = None,
        signing_key: str | None = None,
        storage_factory: Callable[[Settings], Any] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings_factory = settings_factory
        self._store = store
        self.limits = limits or JobLimits()
        self._signing_key = signing_key
        self._storage_factory = storage_factory or _storage
        self._storage: Any = None
        self._settings: Settings | None = None
        self.clock = clock
        self._lock = RLock()

    def settings(self) -> Settings:
        with self._lock:
            if self._settings is None:
                try:
                    self._settings = self.settings_factory()
                except Exception:
                    raise QueryError("jobs_unavailable") from None
            return self._settings

    def store(self) -> JobStore:
        with self._lock:
            if self._store is None:
                settings = self.settings()
                self._store = PostgresJobStore(
                    app_engine_from_url(settings.database_url.get_secret_value())
                )
            return self._store

    def signing_key(self) -> str | None:
        if self._signing_key is not None:
            return self._signing_key
        try:
            key = self.settings().artefact_signing_key
        except QueryError:
            return None
        return None if key is None else key.get_secret_value()

    def storage(self) -> Any:
        with self._lock:
            if self._storage is None:
                self._storage = self._storage_factory(self.settings())
            return self._storage

    def download_url(self, artefact: Artefact) -> str | None:
        key = self.signing_key()
        if key is None or artefact.state != "available" or artefact.expires_at <= self.clock():
            return None
        expires = min(
            artefact.expires_at, self.clock() + timedelta(seconds=self.limits.token_ttl_seconds)
        )
        return download_path(artefact.id, sign(key, artefact.id, expires))


def _storage(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key.get_secret_value(),
        aws_secret_access_key=settings.object_storage_secret_key.get_secret_value(),
        region_name=settings.object_storage_region,
        config=Config(
            connect_timeout=3,
            read_timeout=60,
            retries={"total_max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )


def sse_line(kind: str, seq: int, payload: dict[str, Any]) -> str:
    import json

    return f"id: {seq}\nevent: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"


def event_stream(
    store: JobStore,
    job_id: str,
    after: int,
    *,
    poll: float = POLL_SECONDS,
    heartbeat: float = HEARTBEAT_SECONDS,
    budget: float = STREAM_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[str]:
    """Replay events after ``after`` and follow the job until a terminal event."""
    started = time.monotonic()
    last_sent = time.monotonic()
    cursor = after
    while time.monotonic() - started < budget:
        events = store.events(job_id, cursor)
        for event in events:
            cursor = event.seq
            job = store.get(job_id)
            payload = dict(event.payload)
            payload["job_state"] = None if job is None else job.state
            if job is not None:
                payload["progress"] = job.progress
            yield sse_line(event.kind, event.seq, payload)
            last_sent = time.monotonic()
            if event.kind == "finished":
                return
        if not events:
            job = store.get(job_id)
            if job is None or (job.state in TERMINAL_STATES and not store.events(job_id, cursor)):
                # Finished without a trailing event (or deleted): close the stream.
                yield sse_line(
                    "finished", cursor, {"job_state": None if job is None else job.state}
                )
                return
        if time.monotonic() - last_sent >= heartbeat:
            yield ": keep-alive\n\n"
            last_sent = time.monotonic()
        sleep(poll)


def install_jobs(app: FastAPI, runtime: JobsRuntime) -> None:
    router = APIRouter(prefix="/v1", responses=JOB_ERRORS)

    def _artefacts(store: JobStore, job_id: str) -> list[dict[str, Any]]:
        records = []
        for artefact in store.artefacts(job_id):
            record = artefact.as_dict()
            record["download_url"] = runtime.download_url(artefact)
            records.append(record)
        return records

    @router.post(
        "/exports", status_code=202, response_model=JobCreated, response_model_exclude_unset=True
    )
    async def create_export(
        request: Request,
        body: ExportRequestBody,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
        idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        payload = body.model_dump(exclude_none=True)
        key = payload.pop("idempotency_key", None) or idempotency_key
        if key is not None:
            payload["idempotency_key"] = key
        export = parse_export_request(payload)
        plan = plan_for(export, runtime.limits)
        resolve_geography(plan.geography)  # unknown_region before any row is written
        store = await run_in_threadpool(runtime.store)
        job, created, attached = await run_in_threadpool(
            lambda: store.create(
                client_id=client,
                kind="export",
                queue="export",
                request=export.canonical(),
                request_sha256=export.sha256(),
                plan=plan.canonical(),
                idempotency_key=export.idempotency_key,
            )
        )
        log.info(
            "export job %s client=%s created=%s attached=%s correlation=%s",
            job.id,
            client,
            created,
            attached,
            getattr(request.state, "correlation_id", None) or correlation_id(request),
        )
        return {"job": job.as_dict(), "created": created, "attached": attached}

    @router.get("/jobs", response_model=JobList, response_model_exclude_unset=True)
    async def list_jobs(
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        store = await run_in_threadpool(runtime.store)
        rows = await run_in_threadpool(store.list_for, client, limit)
        return {"jobs": [row.as_dict() for row in rows]}

    @router.get("/jobs/{job_id}", response_model=JobDetail, response_model_exclude_unset=True)
    async def job_detail(
        job_id: str,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        identifier = validate_job_id(job_id)
        store = await run_in_threadpool(runtime.store)
        job = await run_in_threadpool(store.get, identifier, client)
        if job is None:
            raise QueryError("job_not_found")
        chunks = await run_in_threadpool(store.chunks, identifier)
        artefacts = await run_in_threadpool(_artefacts, store, identifier)
        return {
            "job": job.as_dict(),
            "chunks": [chunk.as_dict() for chunk in chunks],
            "artefacts": artefacts,
        }

    @router.get("/jobs/{job_id}/events")
    async def job_events(
        job_id: str,
        request: Request,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        after: int = Query(default=0, ge=0),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        identifier = validate_job_id(job_id)
        store = await run_in_threadpool(runtime.store)
        job = await run_in_threadpool(store.get, identifier, client)
        if job is None:
            raise QueryError("job_not_found")
        start = after
        if last_event_id and last_event_id.isdigit():
            start = max(start, int(last_event_id))
        return StreamingResponse(
            iterate_in_threadpool(event_stream(store, identifier, start)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post(
        "/jobs/{job_id}/cancel", response_model=JobEnvelope, response_model_exclude_unset=True
    )
    async def cancel_job(
        job_id: str,
        body: CancelBody | None = None,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        identifier = validate_job_id(job_id)
        store = await run_in_threadpool(runtime.store)
        version = None if body is None else body.version
        job = await run_in_threadpool(store.cancel, identifier, client, version)
        return {"job": job.as_dict()}

    @router.get("/artefacts/{artefact_id}/download")
    async def download_artefact(artefact_id: str, token: str | None = Query(default=None)) -> Any:
        try:
            identifier = validate_job_id(artefact_id)
        except QueryError:
            raise QueryError("artefact_unavailable") from None
        key = runtime.signing_key()
        if key is None or not verify(key, identifier, token, runtime.clock()):
            raise QueryError("token_invalid")
        store = await run_in_threadpool(runtime.store)
        artefact = await run_in_threadpool(store.artefact, identifier)
        if (
            artefact is None
            or artefact.state != "available"
            or artefact.expires_at <= runtime.clock()
        ):
            raise QueryError("artefact_unavailable")
        settings = runtime.settings()
        client = runtime.storage()

        def open_object() -> Any:
            try:
                return client.get_object(
                    Bucket=settings.object_storage_bucket, Key=artefact.object_key
                )
            except Exception:
                raise QueryError("artefact_unavailable") from None

        response = await run_in_threadpool(open_object)
        body = response["Body"]

        def chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(1024 * 1024)
            finally:
                body.close()

        headers = {
            "Content-Disposition": f'attachment; filename="{artefact.filename}"',
            "Content-Length": str(artefact.bytes),
            "X-Content-SHA256": artefact.sha256,
            "Cache-Control": "private, no-store",
        }
        return StreamingResponse(
            iterate_in_threadpool(chunks()),
            media_type=CONTENT_TYPES.get(artefact.format, "application/octet-stream"),
            headers=headers,
        )

    app.include_router(router)
