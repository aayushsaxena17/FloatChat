"""Stage 2 query endpoints (PRD section 13; plan section 5).

Conventions: versioned prefix, JSON, UTC timestamps, keyset cursors, stable error codes, a
correlation ID on every response, no raw SQL anywhere. Authentication arrives with Stage 7.
"""

import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import boto3
from botocore.config import Config
from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from floatchat_core.config import Settings
from floatchat_core.query.cache import PartCache
from floatchat_core.query.catalogue import QueryCatalogue, engine_from_url
from floatchat_core.query.errors import Detail, QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import BoundingBox, DepthRange, NamedRegion
from floatchat_core.query.router import QueryService
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("floatchat.api")
CORRELATION_HEADER = "X-Correlation-ID"
CORRELATION_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
Geography = NamedRegion | BoundingBox | None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, str]]
    correlation_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class _Loose(BaseModel):
    """A typed shape that later stages may extend; extra keys pass through (ADR-0064)."""

    model_config = ConfigDict(extra="allow")


class TimeInterval(_Loose):
    start: str | None = None
    end: str | None = None


class Environment(_Loose):
    id: str
    name: str
    mode: str
    reference_time: str | None = None
    completed_runs: int
    hot_tier: TimeInterval | None = None
    postgresql_window: TimeInterval | None = None
    latest_run: str | None = None
    ingested_at: str | None = None
    source_retrieved: TimeInterval | None = None


class Box(_Loose):
    west: float
    south: float
    east: float
    north: float


class GeographyInfo(_Loose):
    kind: str
    name: str | None = None
    version: str | None = None
    sha256: str | None = None
    clipped: bool | None = None
    boxes: list[Box] | None = None
    longitude: float | None = None
    latitude: float | None = None
    radius_m: float | None = None


class QcPolicy(_Loose):
    name: str
    version: str
    description: str


class Tile(_Loose):
    west: float
    south: float


class SlotCoverage(_Loose):
    slot: str
    month: str
    tile: Tile
    state: str
    gaps: list[str]
    profiles: int
    levels: int
    parts: int


class CoverageSummary(_Loose):
    requested: TimeInterval
    months: list[str]
    tiles: list[Tile]
    slots_total: int
    slots_covered: int
    slots_empty_verified: int
    slots_missing: int
    missing: list[SlotCoverage]
    estimated_profiles: int
    estimated_levels: int
    partial: bool


class Column(_Loose):
    name: str
    type: str
    unit: str | None = None


class ResultTable(_Loose):
    columns: list[Column]
    rows: list[list[Any]]
    row_count: int
    missing_value_policy: str
    non_finite_values: int


class ChartAxis(_Loose):
    field: str
    label: str
    unit: str | None = None
    reversed: bool = False


class ChartEncodings(_Loose):
    x: ChartAxis
    y: ChartAxis | None = None
    series: ChartAxis


class ChartAxes(_Loose):
    x: ChartAxis
    y: ChartAxis | None = None


class ChartData(_Loose):
    inline: bool
    points: int
    url: str | None = None


class ChartSpec(_Loose):
    """The PRD 11.3 contract; ``plotly`` stays loose (allow-listed trace keys, see chart.py)."""

    type: str
    encodings: ChartEncodings
    axis: ChartAxes
    series: list[str]
    missing_value_policy: str
    aggregation: str
    data: ChartData
    provenance_ref: str
    plotly: dict[str, Any]


class Execution(_Loose):
    source: str | None = None
    elapsed_ms: float | None = None
    rows: int | None = None
    run_ids: list[str] | None = None
    partitions: list[dict[str, Any]] | None = None
    estimated_profiles: int | None = None
    estimated_levels: int | None = None


class Provenance(_Loose):
    source: str
    environment: Environment
    versions: dict[str, Any]
    geography: GeographyInfo | None = None
    coverage: CoverageSummary | None = None
    execution: Execution
    plan_sha256: str | None = None
    result_sha256: str
    application_commit: str
    transformation: str
    attribution: dict[str, str]


class FloatSummary(_Loose):
    platform_number: str
    source: str
    profile_count: int
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    first_cycle: int | None = None
    last_cycle: int | None = None
    last_longitude: float | None = None
    last_latitude: float | None = None


class ProfileHeader(_Loose):
    id: str
    source: str
    source_profile_id: str
    platform_number: str
    cycle_number: int
    direction: str
    observed_at: str
    observation_month: str
    longitude: float
    latitude: float
    level_count: int
    content_hash: str
    last_scientific_run_id: str


class CollectionResponse(_Loose):
    environment: Environment
    time_range: TimeInterval | None = None
    geography: GeographyInfo | None = None
    qc_policy: QcPolicy | None = None
    result: ResultTable
    next_cursor: str | None
    provenance: Provenance


class FloatResponse(_Loose):
    environment: Environment
    time_range: TimeInterval | None = None
    float: FloatSummary
    trajectory: ResultTable
    next_cursor: str | None
    provenance: Provenance


class ProfileResponse(_Loose):
    environment: Environment
    profile: ProfileHeader
    qc_policy: QcPolicy
    levels: ResultTable
    provenance: Provenance


class CoverageResponse(_Loose):
    environment: Environment
    geography: GeographyInfo
    coverage: CoverageSummary
    slots: list[SlotCoverage]


class QueryResponse(_Loose):
    plan: dict[str, Any]
    result: ResultTable
    next_cursor: str | None
    chart: ChartSpec | None
    coverage: CoverageSummary
    partial: bool
    missing: list[SlotCoverage]
    execution: Execution
    interpretation: dict[str, Any]
    provenance: Provenance


class QueryRequest(BaseModel):
    """The ``stage2-plan-v1`` document (documentation shape only).

    Every field is validated by the query engine, which answers ``plan_invalid`` with one
    registered detail per violation; this model therefore never rejects a body itself.
    """

    model_config = ConfigDict(extra="allow")
    dataset: str | None = Field(default="core")
    time_range: dict[str, Any] | None = None
    geography: dict[str, Any] | None = None
    depth_dbar: dict[str, Any] | None = None
    variables: list[str] | None = None
    qc_policy: str | None = "science_ready"
    operation: dict[str, Any] | None = None
    presentation: dict[str, Any] | None = None


ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    504: {"model": ErrorResponse},
}


class QueryRuntime:
    """Builds the query service once, on first use, from the configured environment."""

    def __init__(
        self,
        settings_factory: Callable[[], Settings] = Settings,
        service: QueryService | None = None,
    ) -> None:
        self.settings_factory = settings_factory
        self._service = service
        self._lock = Lock()
        self.limits = QueryLimits()

    def service(self) -> QueryService:
        with self._lock:
            if self._service is None:
                self._service = self._build()
            return self._service

    def start_warmup(self) -> Thread | None:
        """Fill the part cache in the background at start-up (ADR-0058 amendment).

        Readiness is never delayed: the thread builds the service, warms newest months first and
        logs one record; a missing configuration or environment is logged as a skip.
        """
        if not self.limits.warm_cache_on_start:
            return None

        def work() -> None:
            try:
                warm = getattr(self.service(), "warm_cache", None)
                record = warm() if warm is not None else {"skipped": "service has no cache"}
                if "event" not in record:
                    log.info(json.dumps({"event": "warm_cache", **record}))
            except QueryError as error:
                log.info(json.dumps({"event": "warm_cache", "skipped": error.code}))
            except Exception:
                log.exception("warm_cache failed")

        thread = Thread(target=work, name="floatchat-warm-cache", daemon=True)
        thread.start()
        return thread

    def _build(self) -> QueryService:
        try:
            settings = self.settings_factory()
        except Exception:
            raise QueryError("service_unavailable") from None
        if settings.query_database_url is None:
            raise QueryError("service_unavailable")
        engine = engine_from_url(settings.query_database_url.get_secret_value(), self.limits)
        cache = None
        if settings.query_object_cache_dir:
            cache = PartCache(
                Path(settings.query_object_cache_dir),
                self.limits.object_cache_bytes,
                object_fetcher(settings),
            )
        return QueryService(
            QueryCatalogue(engine, self.limits),
            self.limits,
            cache,
            settings.application_commit,
        )


def object_fetcher(settings: Settings) -> Callable[[str, int], bytes]:
    """Verified part download for the cache; also used by scripts/stage2_route_check.py."""
    # One client for the service: boto3 clients are thread-safe and creation is not free.
    client = boto3.client(
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
            max_pool_connections=16,
        ),
    )

    def fetch(object_key: str, byte_count: int) -> bytes:
        try:
            response = client.get_object(Bucket=settings.object_storage_bucket, Key=object_key)
            payload: bytes = response["Body"].read(byte_count + 1)
        except Exception:
            raise QueryError("execution_failed", message="Object storage is unavailable.") from None
        return payload

    return fetch


def correlation_id(request: Request) -> str:
    supplied = request.headers.get(CORRELATION_HEADER, "")
    if CORRELATION_TOKEN.fullmatch(supplied):
        return supplied
    return str(uuid.uuid4())


def _geography(region: str | None, bbox: str | None) -> Geography:
    if region is not None and bbox is not None:
        raise QueryError(
            "invalid_parameter",
            (Detail("geography", "invalid_geography", "use region or bbox, not both"),),
        )
    if region is not None:
        if not 1 <= len(region) <= 128:
            raise QueryError(
                "invalid_parameter", (Detail("region", "invalid_geography", "invalid region"),)
            )
        return NamedRegion(kind="named_region", value=region)
    if bbox is not None:
        try:
            west, south, east, north = (float(part) for part in bbox.split(","))
            return BoundingBox(kind="bbox", west=west, south=south, east=east, north=north)
        except (ValueError, TypeError):
            raise QueryError(
                "invalid_parameter",
                (Detail("bbox", "invalid_geography", "expected west,south,east,north"),),
            ) from None
    return None


def _depth(depth_min: float | None, depth_max: float | None) -> DepthRange | None:
    if depth_min is None and depth_max is None:
        return None
    try:
        depth = DepthRange(
            min=depth_min or 0.0, max=depth_max if depth_max is not None else 12000.0
        )
    except ValueError:
        raise QueryError(
            "invalid_parameter",
            (Detail("depth", "invalid_depth_range", "invalid depth range"),),
        ) from None
    if depth.min >= depth.max:
        raise QueryError(
            "invalid_parameter",
            (Detail("depth", "invalid_depth_range", "min must be below max"),),
        )
    return depth


def _aware(name: str, value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise QueryError(
            "invalid_parameter",
            (Detail(name, "invalid_time_range", "timezone offset required"),),
        )
    return value


def install(app: FastAPI, runtime: QueryRuntime) -> None:
    router = APIRouter(prefix="/v1", responses=ERRORS)

    @app.middleware("http")
    async def correlate(request: Request, call_next: Any) -> Response:
        identifier = correlation_id(request)
        request.state.correlation_id = identifier
        response: Response = await call_next(request)
        response.headers[CORRELATION_HEADER] = identifier
        return response

    @app.exception_handler(QueryError)
    async def query_error(request: Request, error: QueryError) -> JSONResponse:
        identifier = getattr(request.state, "correlation_id", None) or correlation_id(request)
        return JSONResponse(
            error.as_dict(identifier),
            status_code=error.status,
            headers={CORRELATION_HEADER: identifier},
        )

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, error: RequestValidationError) -> JSONResponse:
        identifier = getattr(request.state, "correlation_id", None) or correlation_id(request)
        details = tuple(
            Detail(
                ".".join(str(p) for p in item.get("loc", ()) if p != "query"),
                "invalid_value",
                "invalid value",
            )
            for item in error.errors()[:20]
        )
        body = QueryError("invalid_parameter", details).as_dict(identifier)
        return JSONResponse(body, status_code=400, headers={CORRELATION_HEADER: identifier})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        identifier = getattr(request.state, "correlation_id", None) or correlation_id(request)
        log.exception("unhandled request failure %s", identifier)
        body = QueryError("internal_error").as_dict(identifier)
        return JSONResponse(body, status_code=500, headers={CORRELATION_HEADER: identifier})

    @router.get("/catalog/parameters", response_model=dict[str, Any])
    def catalog_parameters() -> dict[str, Any]:
        return runtime.service().parameters()

    @router.get(
        "/catalog/coverage", response_model=CoverageResponse, response_model_exclude_unset=True
    )
    def catalog_coverage(
        start: datetime | None = None,
        end: datetime | None = None,
        region: str | None = None,
        bbox: str | None = None,
    ) -> Any:
        return runtime.service().coverage(
            start=_aware("start", start), end=_aware("end", end), geography=_geography(region, bbox)
        )

    @router.get("/floats", response_model=CollectionResponse, response_model_exclude_unset=True)
    def floats(
        start: datetime | None = None,
        end: datetime | None = None,
        region: str | None = None,
        bbox: str | None = None,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int | None = None,
    ) -> Any:
        return runtime.service().floats(
            start=_aware("start", start),
            end=_aware("end", end),
            geography=_geography(region, bbox),
            cursor=cursor,
            limit=limit,
        )

    @router.get(
        "/floats/{platform_number}", response_model=FloatResponse, response_model_exclude_unset=True
    )
    def float_detail(
        platform_number: str,
        start: datetime | None = None,
        end: datetime | None = None,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int | None = None,
    ) -> Any:
        return runtime.service().float_detail(
            platform_number,
            start=_aware("start", start),
            end=_aware("end", end),
            cursor=cursor,
            limit=limit,
        )

    @router.get("/profiles", response_model=CollectionResponse, response_model_exclude_unset=True)
    def profiles(
        start: datetime | None = None,
        end: datetime | None = None,
        region: str | None = None,
        bbox: str | None = None,
        platform_number: str | None = Query(default=None, max_length=32),
        depth_min: float | None = None,
        depth_max: float | None = None,
        qc_policy: str = "science_ready",
        cursor: str | None = Query(default=None, max_length=512),
        limit: int | None = None,
    ) -> Any:
        return runtime.service().profiles(
            start=_aware("start", start),
            end=_aware("end", end),
            geography=_geography(region, bbox),
            platform_number=platform_number,
            depth=_depth(depth_min, depth_max),
            qc_policy=qc_policy,
            cursor=cursor,
            limit=limit,
        )

    @router.get(
        "/profiles/{profile_id}", response_model=ProfileResponse, response_model_exclude_unset=True
    )
    def profile(
        profile_id: str,
        qc_policy: str = "science_ready",
        depth_min: float | None = None,
        depth_max: float | None = None,
    ) -> Any:
        return runtime.service().profile(
            profile_id, qc_policy=qc_policy, depth=_depth(depth_min, depth_max)
        )

    @router.post(
        "/query",
        response_model=QueryResponse,
        response_model_exclude_unset=True,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/QueryRequest"}}
                },
            }
        },
    )
    async def query(request: Request) -> Any:
        # The body is read raw so that the size bound and the plan validator see every request;
        # a typed parameter would let FastAPI answer first with a different error shape.
        payload = await request.body()
        if len(payload) > runtime.limits.request_bytes:
            raise QueryError("payload_too_large")
        try:
            document = json.loads(payload)
        except ValueError:
            document = None
        if not isinstance(document, dict):
            raise QueryError(
                "plan_invalid", (Detail("plan", "invalid_value", "JSON object required"),)
            )
        return runtime.service().query(document)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        identifier = getattr(request.state, "correlation_id", None) or correlation_id(request)
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            error.status_code, "internal_error"
        )
        body = QueryError(code).as_dict(identifier)
        return JSONResponse(
            body, status_code=QueryError(code).status, headers={CORRELATION_HEADER: identifier}
        )

    app.include_router(router)

    def openapi_with_plan_schema() -> dict[str, Any]:
        """The request body of ``POST /v1/query`` is documented as the ``QueryRequest`` model."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components["QueryRequest"] = QueryRequest.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_plan_schema  # type: ignore[method-assign]
