"""Stage 6 forecast endpoints (ADR-0085).

``POST /v1/forecasts`` creates a forecast job (kind ``forecast``, queue ``forecast``) and its
definition; ``GET /v1/forecasts`` lists this client's runs; ``GET /v1/forecasts/{run_id}``
returns the run with history, forecast, intervals, backtest, model, warnings and the
interpretation boundary text. The job itself is followed through ``/v1/jobs``.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from fastapi import APIRouter, FastAPI, Header, Query
from floatchat_core.chat.store import app_engine_from_url, validate_client
from floatchat_core.forecast.model import (
    BOUNDARY_TEXT,
    ForecastLimits,
    definition_sha256,
    parse_forecast_request,
)
from floatchat_core.forecast.store import ForecastStore, PostgresForecastStore, validate_run_id
from floatchat_core.query.errors import QueryError
from floatchat_core.query.geography import resolve_geography
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from floatchat_api.jobs_api import CLIENT_HEADER, IDEMPOTENCY_HEADER, JOB_ERRORS, JobsRuntime


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class ForecastRequestBody(BaseModel):
    """``forecast-request-v1`` (ADR-0085)."""

    model_config = ConfigDict(extra="forbid")
    variable: str = Field(pattern="^(temperature|salinity)$")
    geography: dict[str, Any]
    depth_dbar: dict[str, Any] | None = None
    time_range: dict[str, Any] | None = None
    horizon: int = Field(default=3, ge=1, le=12)
    min_profiles: int = Field(default=5, ge=1, le=100)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ForecastRunRecord(_Loose):
    id: str
    definition_id: str
    model_id: str | None = None
    job_id: str | None = None
    horizon: int
    status: str
    reason: str | None = None
    history: dict[str, Any]
    forecast: dict[str, Any]
    backtest: dict[str, Any]
    warnings: list[str]
    limitations: str
    seed: int
    versions: dict[str, Any]
    generated_at: str | None = None
    created_at: str
    updated_at: str


class ForecastDefinitionRecord(_Loose):
    id: str
    definition_sha256: str
    variable: str
    region: str
    depth_dbar: dict[str, Any]
    frequency: str
    aggregation: str
    qc_policy: str
    min_profiles: int
    series_start: str
    series_end: str


class ForecastModelRecord(_Loose):
    id: str
    version: int
    family: str
    order: dict[str, Any]
    training_snapshot: dict[str, Any]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    status: str


class ForecastCreated(_Loose):
    job: dict[str, Any]
    definition: ForecastDefinitionRecord
    created: bool
    attached: bool


class ForecastList(_Loose):
    forecasts: list[ForecastRunRecord]


class ForecastDetail(_Loose):
    run: ForecastRunRecord
    definition: ForecastDefinitionRecord
    model: ForecastModelRecord | None = None
    boundary: str


class ForecastRuntime:
    def __init__(
        self,
        jobs: JobsRuntime,
        store: ForecastStore | None = None,
        limits: ForecastLimits | None = None,
        reference_time: Callable[[], datetime | None] | None = None,
    ) -> None:
        self.jobs = jobs
        self._store = store
        self.limits = limits or ForecastLimits()
        self._reference_time = reference_time
        self._lock = RLock()

    def reference_time(self) -> datetime:
        """The environment's reference time (the data ends there), else this month's start.

        The worker derives the definition from the same reference, so both sides store the
        same definition hash (ADR-0083).
        """
        if self._reference_time is not None:
            try:
                value = self._reference_time()
            except Exception:
                value = None
            if value is not None:
                return value.astimezone(UTC)
        now = datetime.now(UTC)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def store(self) -> ForecastStore:
        with self._lock:
            if self._store is None:
                settings = self.jobs.settings()
                self._store = PostgresForecastStore(
                    app_engine_from_url(settings.database_url.get_secret_value())
                )
            return self._store


def install_forecasts(app: FastAPI, runtime: ForecastRuntime) -> None:
    router = APIRouter(prefix="/v1", responses=JOB_ERRORS)

    @router.post(
        "/forecasts",
        status_code=202,
        response_model=ForecastCreated,
        response_model_exclude_unset=True,
    )
    async def create_forecast(
        body: ForecastRequestBody,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
        idempotency_key: str | None = Header(default=None, alias=IDEMPOTENCY_HEADER),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        payload = body.model_dump(exclude_none=True)
        key = payload.pop("idempotency_key", None) or idempotency_key
        if key is not None:
            payload["idempotency_key"] = key
        request = parse_forecast_request(payload)
        resolve_geography(request.geography)
        jobs_store = await run_in_threadpool(runtime.jobs.store)
        store = await run_in_threadpool(runtime.store)
        reference = await run_in_threadpool(runtime.reference_time)
        document = request.definition(reference, runtime.limits.history_years)
        canonical = request.canonical(reference, runtime.limits.history_years)
        definition = await run_in_threadpool(
            lambda: store.definition(client, document, definition_sha256(document))
        )
        stored_request = {
            k: v
            for k, v in request.model_dump(mode="json", exclude_none=True).items()
            if k != "idempotency_key"
        }
        stored_request["schema"] = "forecast-request-v1"
        job, created, attached = await run_in_threadpool(
            lambda: jobs_store.create(
                client_id=client,
                kind="forecast",
                queue="forecast",
                request=stored_request,
                request_sha256=definition_sha256(canonical),
                plan=canonical,
                idempotency_key=request.idempotency_key,
            )
        )
        return {
            "job": job.as_dict(),
            "definition": definition.as_dict(),
            "created": created,
            "attached": attached,
        }

    @router.get("/forecasts", response_model=ForecastList, response_model_exclude_unset=True)
    async def list_forecasts(
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        store = await run_in_threadpool(runtime.store)
        runs = await run_in_threadpool(store.list_runs, client, limit)
        return {"forecasts": [run.as_dict() for run in runs]}

    @router.get(
        "/forecasts/{run_id}", response_model=ForecastDetail, response_model_exclude_unset=True
    )
    async def forecast_detail(
        run_id: str,
        x_floatchat_client: str | None = Header(default=None, alias=CLIENT_HEADER),
    ) -> Any:
        client = validate_client(x_floatchat_client)
        identifier = validate_run_id(run_id)
        store = await run_in_threadpool(runtime.store)
        run = await run_in_threadpool(store.get_run, identifier, client)
        if run is None:
            raise QueryError("forecast_not_found")
        definition = await run_in_threadpool(store.get_definition, run.definition_id)
        if definition is None:
            raise QueryError("forecast_not_found")
        model = (
            None if run.model_id is None else await run_in_threadpool(store.get_model, run.model_id)
        )
        return {
            "run": run.as_dict(),
            "definition": definition.as_dict(),
            "model": None if model is None else model.as_dict(),
            "boundary": BOUNDARY_TEXT,
        }

    app.include_router(router)
