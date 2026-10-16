"""Job records, the export request schema and the job limits (ADR-0079, ADR-0081)."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..query.errors import Detail, QueryError
from ..query.limits import QueryLimits
from ..query.plan import DepthRange, Geography, QueryPlan, TimeRange, validate_plan

EXPORT_REQUEST_SCHEMA = "export-request-v1"
MANIFEST_SCHEMA = "export-manifest-v1"
IDEMPOTENCY_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
JOB_STATES = (
    "queued",
    "fetching",
    "exporting",
    "analysing",
    "completed",
    "partial",
    "cancelled",
    "failed",
)
ACTIVE_STATES = frozenset({"queued", "fetching", "exporting", "analysing"})
TERMINAL_STATES = frozenset({"completed", "partial", "cancelled", "failed"})
CHUNK_STATES = ("pending", "running", "complete", "reused", "failed", "cancelled")
Format = Literal["csv", "parquet"]


class JobLimits(BaseSettings):
    """Bounds of the job system; environment-overridable with the ``JOBS_`` prefix."""

    model_config = SettingsConfigDict(env_prefix="JOBS_", env_file=None, extra="ignore")

    time_span_days: int = Field(default=7320, ge=1, le=7320)
    artefact_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    lease_seconds: int = Field(default=120, ge=30, le=3600)
    heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    run_execution_seconds: int = Field(default=10800, ge=61, le=43200)
    run_poll_seconds: float = Field(default=15.0, gt=0, le=600)
    overlap_wait_seconds: float = Field(default=10.0, gt=0, le=3600)
    # A job that has just finished a run yields this long before admitting its next one, so a
    # job already waiting for the scope (polling every overlap_wait_seconds) gets it first.
    yield_seconds: float = Field(default=20.0, ge=0, le=3600)
    export_memory_mib: int = Field(default=256, ge=64, le=65536)
    export_threads: int = Field(default=2, ge=1, le=64)
    cache_bytes: int = Field(default=4 * 1024**3, ge=1024 * 1024, le=1024**4)
    object_fetch_seconds: float = Field(default=1800.0, gt=0, le=7200)
    object_fetch_workers: int = Field(default=4, ge=1, le=16)
    orphan_age_seconds: int = Field(default=3600, ge=60, le=86400 * 7)
    listed: int = Field(default=200, ge=1, le=1000)
    max_fetch_chunks: int = Field(default=40, ge=1, le=400)
    # A fetch chunk whose run ends short is re-planned against current coverage and admitted
    # again for the still-missing slots, up to this many runs (PRD section 22, partial retrieval).
    fetch_attempts: int = Field(default=3, ge=1, le=5)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExportRequest(_Model):
    """``export-request-v1``: the plan fields without an operation, plus the format."""

    time_range: TimeRange
    geography: Geography
    depth_dbar: DepthRange | None = None
    variables: tuple[Literal["temperature", "salinity", "pressure"], ...] = (
        "temperature",
        "salinity",
        "pressure",
    )
    qc_policy: Literal["science_ready", "mode_selected", "raw"] = "science_ready"
    format: Format = "parquet"
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_TOKEN.pattern)

    def plan_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataset": "core",
            "time_range": {
                "start": self.time_range.start.isoformat().replace("+00:00", "Z"),
                "end": self.time_range.end.isoformat().replace("+00:00", "Z"),
            },
            "geography": self.geography.model_dump(),
            "variables": list(self.variables),
            "qc_policy": self.qc_policy,
            "operation": {"kind": "profiles", "limit": 1},
            "presentation": {"kind": "table"},
        }
        if self.depth_dbar is not None:
            payload["depth_dbar"] = {"min": self.depth_dbar.min, "max": self.depth_dbar.max}
        return payload

    def canonical(self) -> dict[str, Any]:
        """The request without its idempotency key: two requests with equal canonical forms are
        the same work (attachment, ADR-0079)."""
        document = self.plan_payload()
        document.pop("operation")
        document.pop("presentation")
        document["format"] = self.format
        document["schema"] = EXPORT_REQUEST_SCHEMA
        return document

    def sha256(self) -> str:
        text = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def parse_export_request(payload: Any) -> ExportRequest:
    if not isinstance(payload, dict):
        raise QueryError("plan_invalid", (Detail("request", "invalid_value", "object required"),))
    try:
        return ExportRequest.model_validate(payload)
    except ValidationError as error:
        details = tuple(
            Detail(
                ".".join(str(part) for part in item["loc"]) or "request",
                "invalid_value",
                str(item["msg"])[:200],
            )
            for item in error.errors()[:20]
        )
        raise QueryError("plan_invalid", details) from None


def plan_for(request: ExportRequest, limits: JobLimits | None = None) -> QueryPlan:
    """The validated ``stage2-plan-v1`` behind an export; the span bound is the job's."""
    limits = limits or JobLimits()
    return validate_plan(request.plan_payload(), QueryLimits(time_span_days=limits.time_span_days))


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    queue: str
    client_id: str
    idempotency_key: str | None
    request: dict[str, Any]
    request_sha256: str
    plan: dict[str, Any]
    state: str
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    version: int = 1
    attempts: int = 0
    claimed_by: str | None = None
    lease_until: datetime | None = None
    cancel_requested_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "queue": self.queue,
            "idempotency_key": self.idempotency_key,
            "request": self.request,
            "request_sha256": self.request_sha256,
            "plan": self.plan,
            "state": self.state,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "version": self.version,
            "attempts": self.attempts,
            "cancel_requested_at": _iso(self.cancel_requested_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }


@dataclass(frozen=True)
class JobChunk:
    id: str
    job_id: str
    seq: int
    kind: str
    label: str
    interval_start: datetime | None
    interval_end: datetime | None
    tiles: list[list[int]]
    state: str = "pending"
    attempts: int = 0
    ingestion_run_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "kind": self.kind,
            "label": self.label,
            "interval": None
            if self.interval_start is None or self.interval_end is None
            else {"start": _iso(self.interval_start), "end": _iso(self.interval_end)},
            "tiles": [{"west": west, "south": south} for west, south in self.tiles],
            "state": self.state,
            "attempts": self.attempts,
            "ingestion_run_id": self.ingestion_run_id,
            "evidence": self.evidence,
            "error": self.error,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "payload": self.payload,
            "created_at": _iso(self.created_at),
        }


@dataclass(frozen=True)
class Artefact:
    id: str
    job_id: str
    format: str
    role: str
    object_key: str
    bytes: int
    sha256: str
    row_count: int
    profile_count: int
    manifest: dict[str, Any]
    state: str
    created_at: datetime
    expires_at: datetime
    deleted_at: datetime | None = None

    @property
    def filename(self) -> str:
        return self.object_key.rsplit("/", 1)[-1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "format": self.format,
            "role": self.role,
            "filename": self.filename,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "profile_count": self.profile_count,
            "manifest": self.manifest,
            "state": self.state,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
        }
