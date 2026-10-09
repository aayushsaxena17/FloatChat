"""Query plan ``stage2-plan-v1`` (PRD section 8.1; plan section 4).

Natural-language and form requests converge on this one representation. Validation rejects
unknown fields anywhere, unknown variables, regions, functions and formats, invalid ranges,
unbounded requests and operation/variable mismatches with one registered detail per violation.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import Detail, QueryError
from .limits import QueryLimits

PLAN_SCHEMA = "stage2-plan-v1"
VARIABLES = ("temperature", "salinity", "pressure")
QC_POLICIES = ("science_ready", "mode_selected", "raw")
METRICS = ("mean", "count", "min", "max", "stddev", "median")
GROUP_KEYS = ("month", "day", "profile", "float", "depth_bin", "region")
DEPTH_BIN_SIZES = (10, 25, 50, 100)
PRESENTATIONS = ("table", "line_chart", "scatter", "profile_plot", "ts_diagram", "histogram", "map")
MAX_DEPTH_DBAR = 12000.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeRange(_Model):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timezone offset required")
        return value.astimezone(UTC)


class NamedRegion(_Model):
    kind: Literal["named_region"]
    value: str = Field(min_length=1, max_length=128)


class BoundingBox(_Model):
    kind: Literal["bbox"]
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east

    def envelopes(self) -> tuple[tuple[float, float, float, float], ...]:
        """One envelope, or two when the box crosses the antimeridian (plan section 4.1)."""
        if self.crosses_antimeridian:
            return (
                (self.west, self.south, 180.0, self.north),
                (-180.0, self.south, self.east, self.north),
            )
        return ((self.west, self.south, self.east, self.north),)


class PointRadius(_Model):
    kind: Literal["point_radius"]
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    radius_km: float = Field(gt=0)


Geography = Annotated[NamedRegion | BoundingBox | PointRadius, Field(discriminator="kind")]


class DepthRange(_Model):
    min: float = Field(default=0.0, ge=0, le=MAX_DEPTH_DBAR)
    max: float = Field(gt=0, le=MAX_DEPTH_DBAR)


class ProfilesOperation(_Model):
    kind: Literal["profiles"]
    limit: int | None = Field(default=None, ge=1)
    cursor: str | None = Field(default=None, max_length=512)


class AggregateOperation(_Model):
    kind: Literal["aggregate"]
    group_by: tuple[Literal["month", "day", "profile", "float", "depth_bin", "region"], ...] = ()
    metrics: tuple[Literal["mean", "count", "min", "max", "stddev", "median"], ...]
    unit: Literal["profile", "measurement"] = "profile"
    depth_bin_size: Literal[10, 25, 50, 100] | None = None


class NearestOperation(_Model):
    kind: Literal["nearest"]
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    radius_km: float = Field(gt=0)
    k: int = Field(default=10, ge=1)


Operation = Annotated[
    ProfilesOperation | AggregateOperation | NearestOperation, Field(discriminator="kind")
]


class Presentation(_Model):
    kind: Literal[
        "table", "line_chart", "scatter", "profile_plot", "ts_diagram", "histogram", "map"
    ] = "table"
    bins: int | None = Field(default=None, ge=1)


class QueryPlan(_Model):
    dataset: Literal["core"] = "core"
    time_range: TimeRange
    geography: Geography
    depth_dbar: DepthRange | None = None
    variables: tuple[Literal["temperature", "salinity", "pressure"], ...] = Field(min_length=1)
    qc_policy: Literal["science_ready", "mode_selected", "raw"] = "science_ready"
    operation: Operation
    presentation: Presentation = Presentation()

    def canonical(self) -> dict[str, Any]:
        """The normalized plan: UTC timestamps, ordered variables, defaults made explicit."""
        document = self.model_dump(mode="json", exclude_none=False)
        document["time_range"] = {
            "start": self.time_range.start.isoformat().replace("+00:00", "Z"),
            "end": self.time_range.end.isoformat().replace("+00:00", "Z"),
        }
        document["variables"] = sorted(set(self.variables), key=VARIABLES.index)
        document["plan_schema"] = PLAN_SCHEMA
        return document

    @property
    def plan_sha256(self) -> str:
        text = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    @property
    def ordered_variables(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.variables), key=VARIABLES.index))


def _translate(error: ValidationError) -> list[Detail]:
    details = []
    tags = {"aggregate", "profiles", "nearest", "named_region", "bbox", "point_radius"}
    for item in error.errors():
        # Discriminated unions put the tag into the location; the client sees field paths only.
        parts = [str(part) for part in item["loc"] if str(part) not in tags]
        path = ".".join(parts) or "plan"
        kind = item["type"]
        if kind == "extra_forbidden":
            code, message = "unknown_field", "unknown field"
        elif kind == "missing":
            code, message = "missing_field", "required field missing"
        elif kind in ("literal_error", "enum") and path.startswith("variables"):
            code, message = "unknown_variable", "unknown variable"
        elif kind in ("literal_error", "enum") and (
            path.startswith("operation.metrics") or path.startswith("operation.group_by")
        ):
            code, message = "unknown_function", "unknown metric or group key"
        elif kind in ("literal_error", "enum") and path == "presentation.kind":
            code, message = "disallowed_format", "unsupported presentation"
        elif kind in ("literal_error", "enum") and path == "qc_policy":
            code, message = "invalid_value", "unknown QC policy"
        elif kind == "union_tag_invalid" or kind == "union_tag_not_found":
            code, message = "invalid_value", "unknown kind"
        elif path.startswith("time_range"):
            code, message = "invalid_time_range", "invalid timestamp"
        elif path.startswith("depth_dbar"):
            code, message = "invalid_depth_range", "invalid depth value"
        elif path.startswith("geography"):
            code, message = "invalid_geography", "invalid coordinate"
        else:
            code, message = "invalid_value", "invalid value"
        details.append(Detail(path, code, message))
    return details


def _rules(plan: QueryPlan, limits: QueryLimits) -> list[Detail]:
    details: list[Detail] = []
    span = plan.time_range.end - plan.time_range.start
    if span <= timedelta(0):
        details.append(Detail("time_range", "invalid_time_range", "start must precede end"))
    elif span > timedelta(days=limits.time_span_days):
        details.append(
            Detail(
                "time_range",
                "unbounded_request",
                f"time span exceeds {limits.time_span_days} days",
            )
        )
    if plan.depth_dbar is not None and plan.depth_dbar.min >= plan.depth_dbar.max:
        details.append(Detail("depth_dbar", "invalid_depth_range", "min must be below max"))
    geography = plan.geography
    if isinstance(geography, BoundingBox):
        if geography.south >= geography.north:
            details.append(Detail("geography", "invalid_geography", "south must be below north"))
        if geography.west == geography.east:
            details.append(Detail("geography", "invalid_geography", "west equals east"))
    if isinstance(geography, PointRadius) and geography.radius_km > limits.nearest_radius_km:
        details.append(
            Detail("geography.radius_km", "invalid_geography", "radius exceeds the limit")
        )
    operation = plan.operation
    if isinstance(operation, ProfilesOperation):
        if operation.limit is None:
            details.append(Detail("operation.limit", "unbounded_request", "limit required"))
        elif operation.limit > limits.page_size:
            details.append(
                Detail("operation.limit", "unbounded_request", "limit exceeds the page size")
            )
    if isinstance(operation, NearestOperation):
        if operation.radius_km > limits.nearest_radius_km:
            details.append(
                Detail("operation.radius_km", "invalid_geography", "radius exceeds the limit")
            )
        if operation.k > limits.nearest_k:
            details.append(Detail("operation.k", "unbounded_request", "k exceeds the limit"))
        if plan.presentation.kind not in ("table", "map"):
            details.append(
                Detail(
                    "presentation.kind",
                    "operation_variable_mismatch",
                    "nearest supports table or map",
                )
            )
    if isinstance(operation, AggregateOperation):
        if not operation.metrics:
            details.append(Detail("operation.metrics", "unbounded_request", "metrics required"))
        if len(set(operation.metrics)) != len(operation.metrics):
            details.append(Detail("operation.metrics", "invalid_value", "repeated metric"))
        if len(set(operation.group_by)) != len(operation.group_by):
            details.append(Detail("operation.group_by", "invalid_value", "repeated group key"))
        if ("depth_bin" in operation.group_by) != (operation.depth_bin_size is not None):
            details.append(
                Detail(
                    "operation.depth_bin_size",
                    "invalid_value",
                    "depth_bin_size is required with, and only with, the depth_bin key",
                )
            )
        time_keys = {"month", "day", "profile"} & set(operation.group_by)
        if not time_keys and span > timedelta(days=31):
            details.append(
                Detail(
                    "operation.group_by",
                    "unbounded_request",
                    "an aggregate over more than one month needs a time, day or profile key",
                )
            )
    if plan.qc_policy == "raw" and not isinstance(operation, ProfilesOperation):
        details.append(
            Detail("qc_policy", "operation_variable_mismatch", "raw is only for profile reads")
        )
    presentation = plan.presentation
    variables = set(plan.variables)
    if presentation.kind == "ts_diagram" and not {"temperature", "salinity"} <= variables:
        details.append(
            Detail(
                "presentation.kind",
                "operation_variable_mismatch",
                "ts_diagram needs temperature and salinity",
            )
        )
    if presentation.kind in ("profile_plot", "ts_diagram") and not isinstance(
        operation, ProfilesOperation
    ):
        details.append(
            Detail(
                "presentation.kind",
                "operation_variable_mismatch",
                f"{presentation.kind} needs the profiles operation",
            )
        )
    if presentation.kind in ("line_chart", "histogram") and not isinstance(
        operation, AggregateOperation
    ):
        details.append(
            Detail(
                "presentation.kind",
                "operation_variable_mismatch",
                f"{presentation.kind} needs the aggregate operation",
            )
        )
    if presentation.kind == "line_chart" and isinstance(operation, AggregateOperation):
        if not {"month", "day"} & set(operation.group_by):
            details.append(
                Detail(
                    "presentation.kind",
                    "operation_variable_mismatch",
                    "line_chart needs a month or day group key",
                )
            )
    if presentation.bins is not None:
        if presentation.kind != "histogram":
            details.append(Detail("presentation.bins", "invalid_value", "bins is for histograms"))
        elif presentation.bins > limits.histogram_bins:
            details.append(
                Detail("presentation.bins", "unbounded_request", "bins exceeds the limit")
            )
    if presentation.kind == "map" and isinstance(operation, AggregateOperation):
        details.append(
            Detail(
                "presentation.kind",
                "operation_variable_mismatch",
                "map needs the profiles or nearest operation",
            )
        )
    if presentation.kind == "scatter" and not isinstance(operation, AggregateOperation):
        details.append(
            Detail(
                "presentation.kind",
                "operation_variable_mismatch",
                "scatter needs the aggregate operation",
            )
        )
    return details


def validate_plan(payload: Any, limits: QueryLimits | None = None) -> QueryPlan:
    """Parse and validate a plan document; raise ``plan_invalid`` with every violation."""
    limits = limits or QueryLimits()
    if not isinstance(payload, dict):
        raise QueryError("plan_invalid", (Detail("plan", "invalid_value", "object required"),))
    try:
        plan = QueryPlan.model_validate(payload)
    except ValidationError as error:
        raise QueryError("plan_invalid", tuple(_translate(error))) from None
    details = _rules(plan, limits)
    if details:
        raise QueryError("plan_invalid", tuple(details))
    return plan


CURSOR_FIELDS = {"profile": ("t", "id"), "float": ("platform_number",)}


def encode_cursor(kind: str, **fields: Any) -> str:
    if tuple(sorted(fields)) != tuple(sorted(CURSOR_FIELDS[kind])):
        raise ValueError("cursor fields")
    document = {"kind": kind}
    for name, value in fields.items():
        document[name] = value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
    text = json.dumps(document, sort_keys=True)
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, kind: str) -> dict[str, Any]:
    """Keyset cursor round trip; tampering yields ``invalid_cursor`` (plan section 5.1)."""
    try:
        if len(cursor) > 512:
            raise ValueError
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if (
            not isinstance(document, dict)
            or document.get("kind") != kind
            or set(document) != {"kind", *CURSOR_FIELDS[kind]}
        ):
            raise ValueError
        result: dict[str, Any] = {}
        for name in CURSOR_FIELDS[kind]:
            value = document[name]
            if not isinstance(value, str) or not value:
                raise ValueError
            if name == "t":
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ValueError
                result[name] = parsed.astimezone(UTC)
            elif name == "id":
                if len(value) != 36:
                    raise ValueError
                result[name] = value
            else:
                if len(value) > 128:
                    raise ValueError
                result[name] = value
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise QueryError("invalid_cursor") from None
    return result
