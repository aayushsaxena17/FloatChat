"""Forecast request schema, limits and records (ADR-0082, ADR-0083)."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..ingestion.planning import shift_months
from ..query.errors import Detail, QueryError
from ..query.plan import DepthRange, NamedRegion, TimeRange

FORECAST_REQUEST_SCHEMA = "forecast-request-v1"
SNAPSHOT_SCHEMA = "series-snapshot-v1"
BOUNDARY_TEXT = (
    "This is a statistical extrapolation of a derived observational series (ARIMA/SARIMA on "
    "monthly profile-balanced means). It is not a physics-based ocean forecast and must not "
    "replace an operational ocean model."
)
Variable = Literal["temperature", "salinity"]


class ForecastLimits(BaseSettings):
    """Eligibility, backtest and search bounds; environment-overridable with ``FORECAST_``."""

    model_config = SettingsConfigDict(env_prefix="FORECAST_", env_file=None, extra="ignore")

    min_months: int = Field(default=36, ge=24, le=600)
    max_missing_fraction: float = Field(default=0.2, ge=0, le=0.5)
    max_gap_months: int = Field(default=2, ge=0, le=12)
    history_years: int = Field(default=10, ge=3, le=20)
    folds: int = Field(default=12, ge=4, le=60)
    horizons: tuple[int, ...] = (1, 2, 3)
    candidates: int = Field(default=3, ge=1, le=10)
    improvement: float = Field(default=0.05, ge=0, le=0.5)
    seed: int = 20261016
    max_orders: int = Field(default=144, ge=1, le=1000)
    # "full" is the 144-order grid of ADR-0084; "small" is a six-order subset for tests and
    # quick checks (the report says which grid it used).
    grid: Literal["full", "small"] = "full"
    fit_maxiter: int = Field(default=50, ge=10, le=500)
    season: int = 12


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ForecastRequest(_Model):
    """``forecast-request-v1``: the forecastable unit of PRD section 12.1 plus the horizon."""

    variable: Variable
    geography: NamedRegion
    depth_dbar: DepthRange = DepthRange(min=0.0, max=100.0)
    time_range: TimeRange | None = None
    horizon: int = Field(default=3, ge=1, le=12)
    min_profiles: int = Field(default=5, ge=1, le=100)
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$")

    def resolved_range(self, reference: datetime, years: int) -> TimeRange:
        if self.time_range is not None:
            return self.time_range
        end = reference.astimezone(UTC)
        return TimeRange(start=shift_months(end, -12 * years), end=end)

    def definition(self, reference: datetime, years: int) -> dict[str, Any]:
        """The series definition without the horizon (one definition, many runs)."""
        span = self.resolved_range(reference, years)
        return {
            "schema": FORECAST_REQUEST_SCHEMA,
            "variable": self.variable,
            "region": self.geography.value,
            "depth_dbar": {"min": self.depth_dbar.min, "max": self.depth_dbar.max},
            "frequency": "monthly",
            "aggregation": "profile_balanced_mean",
            "qc_policy": "science_ready",
            "min_profiles": self.min_profiles,
            "series_start": span.start.isoformat().replace("+00:00", "Z"),
            "series_end": span.end.isoformat().replace("+00:00", "Z"),
        }

    def canonical(self, reference: datetime, years: int) -> dict[str, Any]:
        document = self.definition(reference, years)
        document["horizon"] = self.horizon
        return document


def definition_sha256(definition: dict[str, Any]) -> str:
    text = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def parse_forecast_request(payload: Any) -> ForecastRequest:
    if not isinstance(payload, dict):
        raise QueryError("plan_invalid", (Detail("request", "invalid_value", "object required"),))
    try:
        request = ForecastRequest.model_validate(payload)
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
    if request.time_range is not None and request.time_range.start >= request.time_range.end:
        raise QueryError(
            "plan_invalid",
            (Detail("time_range", "invalid_time_range", "start must precede end"),),
        )
    return request


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Definition:
    id: str
    client_id: str
    definition_sha256: str
    request: dict[str, Any]
    variable: str
    region: str
    depth_min: float
    depth_max: float
    min_profiles: int
    series_start: datetime
    series_end: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "definition_sha256": self.definition_sha256,
            "variable": self.variable,
            "region": self.region,
            "depth_dbar": {"min": self.depth_min, "max": self.depth_max},
            "frequency": "monthly",
            "aggregation": "profile_balanced_mean",
            "qc_policy": "science_ready",
            "min_profiles": self.min_profiles,
            "series_start": _iso(self.series_start),
            "series_end": _iso(self.series_end),
            "created_at": _iso(self.created_at),
        }


@dataclass(frozen=True)
class ForecastModel:
    id: str
    definition_id: str
    version: int
    family: str
    model_order: dict[str, Any]
    training_snapshot: dict[str, Any]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    status: str
    artefact_key: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "definition_id": self.definition_id,
            "version": self.version,
            "family": self.family,
            "order": self.model_order,
            "training_snapshot": self.training_snapshot,
            "metrics": self.metrics,
            "diagnostics": self.diagnostics,
            "status": self.status,
            "artefact_key": self.artefact_key,
            "created_at": _iso(self.created_at),
        }


@dataclass(frozen=True)
class ForecastRun:
    id: str
    definition_id: str
    model_id: str | None
    job_id: str | None
    client_id: str
    horizon: int
    status: str
    reason: str | None
    history: dict[str, Any]
    forecast: dict[str, Any]
    backtest: dict[str, Any]
    warnings: list[str]
    limitations: str
    seed: int
    versions: dict[str, Any]
    generated_at: datetime | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "definition_id": self.definition_id,
            "model_id": self.model_id,
            "job_id": self.job_id,
            "horizon": self.horizon,
            "status": self.status,
            "reason": self.reason,
            "history": self.history,
            "forecast": self.forecast,
            "backtest": self.backtest,
            "warnings": self.warnings,
            "limitations": self.limitations,
            "seed": self.seed,
            "versions": self.versions,
            "generated_at": _iso(self.generated_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
