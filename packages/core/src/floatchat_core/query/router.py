"""Coverage router and query service (PRD section 8.3; plan section 6).

One ``QueryService`` serves the catalogue, collection and ``POST /v1/query`` endpoints. It
validates, resolves geography, proves coverage from committed receipts, estimates cost, picks
PostgreSQL or DuckDB, executes under the deadline, sanitises, charts and attaches provenance.
Missing coverage is labelled; no chunk, job or upstream request is ever created here.
"""

import json
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import Select

from ..ingestion.numeric import Rejection
from ..ingestion.planning import Interval
from . import chart, compile_duckdb, compile_sql, provenance
from .cache import PartCache
from .catalogue import Coverage, EnvironmentInfo, QueryCatalogue, translate_error
from .errors import Detail, QueryError
from .geography import ResolvedGeography, resolve_geography
from .limits import QueryLimits
from .plan import (
    DEPTH_BIN_SIZES,
    GROUP_KEYS,
    METRICS,
    PLAN_SCHEMA,
    PRESENTATIONS,
    QC_POLICIES,
    VARIABLES,
    AggregateOperation,
    BoundingBox,
    DepthRange,
    NamedRegion,
    NearestOperation,
    PointRadius,
    ProfilesOperation,
    QueryPlan,
    decode_cursor,
    encode_cursor,
    validate_plan,
)
from .policy import AGGREGATION_UNITS, describe
from .regions import load_regions
from .sanitize import ColumnSpec, SanitizedResult, sanitize, unit_for

log = logging.getLogger("floatchat.query")

PROFILE_COLUMNS = (
    ColumnSpec("id", "string"),
    ColumnSpec("source", "string"),
    ColumnSpec("source_profile_id", "string"),
    ColumnSpec("platform_number", "string"),
    ColumnSpec("cycle_number", "integer"),
    ColumnSpec("direction", "string"),
    ColumnSpec("observed_at", "timestamp"),
    ColumnSpec("observation_month", "date"),
    ColumnSpec("longitude", "number", "degrees_east"),
    ColumnSpec("latitude", "number", "degrees_north"),
    ColumnSpec("level_count", "integer"),
    ColumnSpec("content_hash", "string"),
    ColumnSpec("last_scientific_run_id", "string"),
)
FLOAT_COLUMNS = (
    ColumnSpec("platform_number", "string"),
    ColumnSpec("source", "string"),
    ColumnSpec("profile_count", "integer"),
    ColumnSpec("first_observed_at", "timestamp"),
    ColumnSpec("last_observed_at", "timestamp"),
    ColumnSpec("first_cycle", "integer"),
    ColumnSpec("last_cycle", "integer"),
    ColumnSpec("last_longitude", "number", "degrees_east"),
    ColumnSpec("last_latitude", "number", "degrees_north"),
)
TRAJECTORY_COLUMNS = (
    ColumnSpec("id", "string"),
    ColumnSpec("cycle_number", "integer"),
    ColumnSpec("direction", "string"),
    ColumnSpec("observed_at", "timestamp"),
    ColumnSpec("longitude", "number", "degrees_east"),
    ColumnSpec("latitude", "number", "degrees_north"),
)
LEVEL_CHART_COLUMNS = (
    ColumnSpec("profile_id", "string"),
    ColumnSpec("level_index", "integer"),
    ColumnSpec("pressure", "number", "dbar"),
    ColumnSpec("temperature", "number", "degree_C"),
    ColumnSpec("salinity", "number", "1"),
)
VARIABLE_DESCRIPTIONS = {
    "pressure": "Sea pressure, the vertical coordinate",
    "temperature": "In-situ temperature (ITS-90)",
    "salinity": "Practical salinity (PSS-78), dimensionless",
}
RAW_SUFFIXES = (
    "",
    "_adjusted",
    "_qc",
    "_adjusted_qc",
    "_error",
    "_original_error",
    "_unit",
    "_data_mode",
)
DEFAULT_REGION = NamedRegion(kind="named_region", value="Indian Ocean")
Geography = NamedRegion | BoundingBox | PointRadius


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _interval(start: datetime, end: datetime) -> Interval:
    try:
        return Interval(start.astimezone(UTC), end.astimezone(UTC))
    except Rejection:
        raise QueryError(
            "invalid_parameter",
            (Detail("time_range", "invalid_time_range", "start must precede end"),),
        ) from None


def _level_columns(policy: str) -> tuple[ColumnSpec, ...]:
    columns = [ColumnSpec("level_index", "integer")]
    for variable in VARIABLES:
        unit = unit_for(variable)
        if policy == "raw":
            for suffix in RAW_SUFFIXES:
                name = variable + suffix
                numeric = suffix in ("", "_adjusted", "_error", "_original_error")
                columns.append(ColumnSpec(name, "number" if numeric else "string", unit_for(name)))
        else:
            columns += [
                ColumnSpec(variable, "number", unit),
                ColumnSpec(variable + "_qc", "string"),
                ColumnSpec(variable + "_data_mode", "string"),
                ColumnSpec(variable + "_unit", "string"),
            ]
    return tuple(columns)


def _aggregate_columns(names: Sequence[str]) -> tuple[ColumnSpec, ...]:
    columns = []
    for name in names:
        if name == "depth_bin":
            columns.append(ColumnSpec(name, "number", "dbar"))
        elif name in GROUP_KEYS:
            columns.append(ColumnSpec(name, "string"))
        elif name.endswith("_count"):
            columns.append(ColumnSpec(name, "integer"))
        else:
            columns.append(ColumnSpec(name, "number", unit_for(name)))
    return tuple(columns)


def _depth_text(plan: QueryPlan) -> str:
    if plan.depth_dbar is None:
        return ""
    return f", depth {plan.depth_dbar.min}-{plan.depth_dbar.max} dbar"


class QueryService:
    def __init__(
        self,
        catalogue: QueryCatalogue,
        limits: QueryLimits | None = None,
        cache: PartCache | None = None,
        application_commit: str = "unknown",
    ) -> None:
        self.catalogue = catalogue
        self.limits = limits or QueryLimits()
        self.cache = cache
        self.application_commit = application_commit

    # ----- helpers -------------------------------------------------------------------------

    def _rows(self, statement: Select[Any]) -> list[dict[str, Any]]:
        try:
            with self.catalogue.engine.connect() as connection:
                return [dict(row) for row in connection.execute(statement).mappings().all()]
        except SQLAlchemyError as error:
            raise translate_error(error) from None

    def _default_interval(
        self, environment: EnvironmentInfo, start: datetime | None, end: datetime | None
    ) -> Interval:
        if start is None or end is None:
            window = environment.window
            if window is None:
                raise QueryError("coverage_missing", message="No completed run defines a window.")
            start = start or window.start
            end = end or window.end
        return _interval(start, end)

    def _page(self, requested: int | None) -> int:
        if requested is None:
            return self.limits.default_page_size
        if requested < 1 or requested > self.limits.page_size:
            raise QueryError(
                "invalid_parameter",
                (Detail("limit", "unbounded_request", "limit outside 1..page_size"),),
            )
        return requested

    def _coverage(
        self, environment: EnvironmentInfo, interval: Interval, geography: ResolvedGeography
    ) -> Coverage:
        tiles = self.catalogue.tiles_for(geography)
        return self.catalogue.coverage(environment.id, interval, tiles)

    @staticmethod
    def _profile_cursor(cursor: str | None) -> tuple[datetime, str] | None:
        if not cursor:
            return None
        decoded = decode_cursor(cursor, "profile")
        return decoded["t"], decoded["id"]

    @staticmethod
    def _next_profile_cursor(rows: list[dict[str, Any]], page: int) -> str | None:
        if len(rows) <= page:
            return None
        last = rows[page - 1]
        return encode_cursor("profile", t=last["observed_at"], id=str(last["id"]))

    # ----- catalogue ------------------------------------------------------------------------

    def parameters(self) -> dict[str, Any]:
        return {
            "plan_schema": PLAN_SCHEMA,
            "dataset": {"core": {"source": "argovis", "mapping": "argovis-core-v1"}},
            "variables": [
                {
                    "name": variable,
                    "unit": unit_for(variable),
                    "description": VARIABLE_DESCRIPTIONS[variable],
                    "columns": [variable + suffix for suffix in RAW_SUFFIXES],
                }
                for variable in VARIABLES
            ],
            "qc_policies": [describe(policy) for policy in QC_POLICIES],
            "aggregation_units": [
                {"name": name, "description": text} for name, text in AGGREGATION_UNITS.items()
            ],
            "operations": {
                "profiles": {"limit": "1..page_size", "cursor": "opaque keyset cursor"},
                "aggregate": {
                    "group_by": list(GROUP_KEYS),
                    "metrics": list(METRICS),
                    "depth_bin_sizes": list(DEPTH_BIN_SIZES),
                },
                "nearest": {
                    "radius_km": self.limits.nearest_radius_km,
                    "k": self.limits.nearest_k,
                },
            },
            "presentations": list(PRESENTATIONS),
            "geography": {
                "named_region": [record.public() for record in load_regions()],
                "bbox": "west, south, east, north in degrees; west > east crosses the antimeridian",
                "point_radius": "longitude, latitude, radius_km",
                "membership": "planar ST_Covers on WGS84 geometry (the Stage 1 rule); "
                "distances are geodesic",
            },
            "time_range": "UTC ISO-8601 with offset; start inclusive, end exclusive",
            "limits": self.limits.public(),
            "attribution": {
                "argo": "https://doi.org/10.17882/42182",
                "argovis": "https://doi.org/10.1175/JTECH-D-19-0041.1",
                "regions": "Flanders Marine Institute (2018), IHO Sea Areas v3, "
                "https://doi.org/10.14284/323, CC-BY 4.0",
            },
        }

    def coverage(
        self, *, start: datetime | None, end: datetime | None, geography: Geography | None
    ) -> dict[str, Any]:
        environment = self.catalogue.environment()
        interval = self._default_interval(environment, start, end)
        resolved = resolve_geography(geography or DEFAULT_REGION)
        coverage = self._coverage(environment, interval, resolved)
        return {
            "environment": environment.describe(),
            "geography": resolved.describe(),
            "coverage": coverage.describe(),
            "slots": [slot.describe() for slot in coverage.slots],
        }

    # ----- collections ----------------------------------------------------------------------

    def floats(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        geography: Geography | None,
        cursor: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        environment = self.catalogue.environment()
        interval = self._default_interval(environment, start, end)
        resolved = resolve_geography(geography) if geography is not None else None
        page = self._page(limit)
        after = decode_cursor(cursor, "float")["platform_number"] if cursor else None
        rows = self._rows(
            compile_sql.floats_statement(
                interval.start, interval.end, resolved, limit=page, after=after
            )
        )
        next_cursor = None
        if len(rows) > page:
            rows = rows[:page]
            next_cursor = encode_cursor("float", platform_number=rows[-1]["platform_number"])
        result = sanitize(rows, FLOAT_COLUMNS, self.limits)
        return {
            "environment": environment.describe(),
            "time_range": {"start": _iso(interval.start), "end": _iso(interval.end)},
            "geography": None if resolved is None else resolved.describe(),
            "result": result.as_dict(),
            "next_cursor": next_cursor,
        }

    def float_detail(
        self,
        platform_number: str,
        *,
        start: datetime | None,
        end: datetime | None,
        cursor: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        environment = self.catalogue.environment()
        interval = self._default_interval(environment, start, end)
        if not 1 <= len(platform_number.encode()) <= 32:
            raise QueryError("not_found")
        summary = self._rows(
            compile_sql.floats_statement(
                interval.start, interval.end, None, limit=1, platform_number=platform_number
            )
        )
        if not summary:
            raise QueryError("not_found")
        page = min(self._page(limit), self.limits.trajectory_points)
        rows = self._rows(
            compile_sql.trajectory_statement(
                platform_number,
                interval.start,
                interval.end,
                limit=page,
                after=self._profile_cursor(cursor),
            )
        )
        next_cursor = self._next_profile_cursor(rows, page)
        rows = rows[:page]
        head = sanitize(summary, FLOAT_COLUMNS, self.limits)
        trajectory = sanitize(rows, TRAJECTORY_COLUMNS, self.limits)
        return {
            "environment": environment.describe(),
            "time_range": {"start": _iso(interval.start), "end": _iso(interval.end)},
            "float": dict(zip([c.name for c in FLOAT_COLUMNS], head.rows[0], strict=True)),
            "trajectory": trajectory.as_dict(),
            "next_cursor": next_cursor,
        }

    def profiles(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        geography: Geography | None,
        platform_number: str | None,
        depth: DepthRange | None,
        qc_policy: str,
        cursor: str | None,
        limit: int | None,
    ) -> dict[str, Any]:
        environment = self.catalogue.environment()
        interval = self._default_interval(environment, start, end)
        page = self._page(limit)
        plan = validate_plan(
            {
                "time_range": {"start": _iso(interval.start), "end": _iso(interval.end)},
                "geography": (geography or DEFAULT_REGION).model_dump(),
                "depth_dbar": None if depth is None else depth.model_dump(),
                "variables": ["pressure"],
                "qc_policy": qc_policy,
                "operation": {"kind": "profiles", "limit": page, "cursor": cursor},
            },
            self.limits,
        )
        resolved = resolve_geography(plan.geography)
        statement = compile_sql.profiles_statement(
            plan, resolved, limit=page, after=self._profile_cursor(cursor)
        )
        if platform_number is not None:
            statement = statement.where(compile_sql.profile.c.platform_number == platform_number)
        rows = self._rows(statement)
        next_cursor = self._next_profile_cursor(rows, page)
        rows = rows[:page]
        result = sanitize(rows, PROFILE_COLUMNS, self.limits)
        return {
            "environment": environment.describe(),
            "time_range": {"start": _iso(interval.start), "end": _iso(interval.end)},
            "geography": resolved.describe(),
            "qc_policy": describe(qc_policy),
            "result": result.as_dict(),
            "next_cursor": next_cursor,
        }

    def profile(
        self, profile_id: str, *, qc_policy: str, depth: DepthRange | None
    ) -> dict[str, Any]:
        try:
            identifier = uuid.UUID(profile_id)
        except ValueError:
            raise QueryError("not_found") from None
        if qc_policy not in QC_POLICIES:
            raise QueryError(
                "invalid_parameter", (Detail("qc_policy", "invalid_value", "unknown QC policy"),)
            )
        environment = self.catalogue.environment()
        header = self._rows(compile_sql.profile_statement(identifier))
        if not header:
            raise QueryError("not_found")
        levels = self._rows(
            compile_sql.levels_statement(
                identifier,
                header[0]["observation_month"],
                policy=qc_policy,
                depth=depth,
                limit=self.limits.profile_levels,
            )
        )
        head = sanitize(header, PROFILE_COLUMNS, self.limits)
        body = sanitize(levels, _level_columns(qc_policy), self.limits)
        return {
            "environment": environment.describe(),
            "profile": dict(zip([c.name for c in PROFILE_COLUMNS], head.rows[0], strict=True)),
            "qc_policy": describe(qc_policy),
            "levels": body.as_dict(),
        }

    # ----- POST /v1/query ------------------------------------------------------------------

    def query(self, payload: Any) -> dict[str, Any]:
        started = time.monotonic()
        plan = validate_plan(payload, self.limits)
        geography = resolve_geography(plan.geography)
        environment = self.catalogue.environment()
        interval = _interval(plan.time_range.start, plan.time_range.end)
        coverage = self._coverage(environment, interval, geography)
        if not coverage.slots or all(slot.state == "missing" for slot in coverage.slots):
            raise QueryError("coverage_missing")
        execution: dict[str, Any] = {}
        operation = plan.operation
        next_cursor: str | None = None
        if isinstance(operation, ProfilesOperation):
            result, next_cursor, transformation = self._profiles_operation(
                plan, geography, execution
            )
        elif isinstance(operation, NearestOperation):
            result, transformation = self._nearest_operation(plan, geography, execution)
        else:
            result, transformation = self._aggregate_operation(plan, geography, coverage, execution)
        execution["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        execution["rows"] = len(result.rows)
        chart_spec = chart.compile_chart(plan, result, self.limits, transformation)
        record = provenance.build(
            plan=plan,
            environment=environment,
            geography=geography,
            coverage=coverage,
            execution=execution,
            rows=result.rows,
            application_commit=self.application_commit,
            transformation=transformation,
        )
        log.info(
            json.dumps(
                {
                    "event": "query",
                    "plan_sha256": plan.plan_sha256,
                    "source": execution.get("source"),
                    "elapsed_ms": execution["elapsed_ms"],
                    "rows": execution["rows"],
                    "partial": coverage.partial,
                    "result_sha256": record["result_sha256"],
                }
            )
        )
        return {
            "plan": plan.canonical(),
            "result": result.as_dict(),
            "next_cursor": next_cursor,
            "chart": chart_spec,
            "coverage": coverage.describe(),
            "partial": coverage.partial,
            "missing": [slot.describe() for slot in coverage.missing],
            "execution": execution,
            "interpretation": {
                "time_range": plan.canonical()["time_range"],
                "geography": geography.describe(),
                "depth_dbar": None if plan.depth_dbar is None else plan.depth_dbar.model_dump(),
                "variables": list(plan.ordered_variables),
                "qc_policy": describe(plan.qc_policy),
                "operation": plan.operation.model_dump(),
                "presentation": plan.presentation.model_dump(),
                "transformation": transformation,
            },
            "provenance": record,
        }

    def _profiles_operation(
        self, plan: QueryPlan, geography: ResolvedGeography, execution: dict[str, Any]
    ) -> tuple[SanitizedResult, str | None, str]:
        assert isinstance(plan.operation, ProfilesOperation)
        operation = plan.operation
        page = operation.limit or self.limits.default_page_size
        rows = self._rows(
            compile_sql.profiles_statement(
                plan, geography, limit=page, after=self._profile_cursor(operation.cursor)
            )
        )
        next_cursor = self._next_profile_cursor(rows, page)
        rows = rows[:page]
        execution["source"] = "postgresql"
        execution["run_ids"] = sorted({str(row["last_scientific_run_id"]) for row in rows})
        if plan.presentation.kind in ("profile_plot", "ts_diagram"):
            if page > self.limits.chart_series:
                raise QueryError(
                    "result_too_large",
                    message="Profile charts are bounded to chart_series profiles per request.",
                )
            policy = "mode_selected" if plan.qc_policy == "raw" else plan.qc_policy
            level_rows: list[dict[str, Any]] = []
            for row in rows:
                for level in self._rows(
                    compile_sql.levels_statement(
                        row["id"],
                        row["observation_month"],
                        policy=policy,
                        depth=plan.depth_dbar,
                        limit=self.limits.profile_levels,
                    )
                ):
                    level_rows.append(
                        {
                            "profile_id": str(row["id"]),
                            "level_index": level["level_index"],
                            "pressure": level["pressure"],
                            "temperature": level["temperature"],
                            "salinity": level["salinity"],
                        }
                    )
            transformation = (
                f"levels of {len(rows)} profiles with qc-policy-v1/{policy}" + _depth_text(plan)
            )
            return (
                sanitize(level_rows, LEVEL_CHART_COLUMNS, self.limits),
                next_cursor,
                transformation,
            )
        transformation = "profile headers newest first" + (
            f", with at least one level in {plan.depth_dbar.min}-{plan.depth_dbar.max} dbar"
            if plan.depth_dbar
            else ""
        )
        return sanitize(rows, PROFILE_COLUMNS, self.limits), next_cursor, transformation

    def _nearest_operation(
        self, plan: QueryPlan, geography: ResolvedGeography, execution: dict[str, Any]
    ) -> tuple[SanitizedResult, str]:
        assert isinstance(plan.operation, NearestOperation)
        operation = plan.operation
        rows = self._rows(compile_sql.nearest_statement(plan, geography))
        execution["source"] = "postgresql"
        execution["run_ids"] = sorted({str(row["last_scientific_run_id"]) for row in rows})
        columns = (*PROFILE_COLUMNS, ColumnSpec("distance_m", "number", "m"))
        transformation = (
            f"nearest {operation.k} profiles within {operation.radius_km} km of "
            f"({operation.longitude}, {operation.latitude}) by geodesic distance"
        )
        return sanitize(rows, columns, self.limits), transformation

    def _aggregate_operation(
        self,
        plan: QueryPlan,
        geography: ResolvedGeography,
        coverage: Coverage,
        execution: dict[str, Any],
    ) -> tuple[SanitizedResult, str]:
        assert isinstance(plan.operation, AggregateOperation)
        operation = plan.operation
        estimate = coverage.estimated_levels
        execution["estimated_levels"] = estimate
        execution["estimated_profiles"] = coverage.estimated_profiles
        unit = "profiles (profile-balanced)" if operation.unit == "profile" else "levels"
        description = (
            f"{','.join(operation.metrics)} of {','.join(plan.ordered_variables)}"
            + (f" by {','.join(operation.group_by)}" if operation.group_by else "")
            + f" over {unit} with qc-policy-v1/{plan.qc_policy}"
            + _depth_text(plan)
        )
        names = self._aggregate_names(plan)
        if estimate <= self.limits.postgres_level_budget:
            rows = self._rows(
                compile_sql.aggregate_statement(plan, geography, max_rows=self.limits.max_rows)
            )
            if len(rows) > self.limits.max_rows:
                raise QueryError("result_too_large")
            execution["source"] = "postgresql"
            return (
                sanitize(rows, _aggregate_columns(names), self.limits),
                description + ", source postgresql",
            )
        if estimate > self.limits.duckdb_level_budget:
            raise QueryError("cost_over_budget")
        if self.cache is None:
            raise QueryError(
                "cost_over_budget", message="The DuckDB route is not configured on this service."
            )
        if coverage.object_bytes > self.limits.object_fetch_bytes:
            raise QueryError(
                "cost_over_budget", message="The parts to scan exceed the object byte budget."
            )
        selected = self._rows(
            compile_sql.profile_slot_statement(
                plan, geography, [slot.logical_key for slot in coverage.covered]
            )
        )
        members = compile_duckdb.members_table(selected, coverage.manifests)
        parts = [part for slot in coverage.covered for part in slot.parts]
        partitions = [{"id": str(part.partition_id), "sha256": part.sha256} for part in parts]
        # The object fill has its own byte and time budgets (plan section 4.4); the query
        # timeout bounds the DuckDB execution that follows.
        fill = self.cache.fill(
            [(part.key, part.sha256, part.byte_count) for part in parts],
            workers=self.limits.object_fetch_workers,
            deadline_seconds=self.limits.object_fetch_seconds,
        )
        execution["object_fetch_ms"] = round(fill.seconds * 1000, 1)
        execution["objects_fetched"] = fill.fetched
        execution["objects_reused"] = fill.reused
        statement = compile_duckdb.aggregate_statement(
            plan, label=geography.label, max_rows=self.limits.max_rows
        )
        try:
            raw_rows = self._run_duckdb(statement, fill.paths, members)
        except QueryError as error:
            # A cold fill just wrote the files it scans; one more attempt runs over warm files
            # within the same execution deadline (gate known issue: cold-path deadline).
            if error.code != "statement_timeout" or fill.fetched == 0:
                raise
            execution["retried_after_cold_fill"] = True
            raw_rows = self._run_duckdb(statement, fill.paths, members)
        if len(raw_rows) > self.limits.max_rows:
            raise QueryError("result_too_large")
        rows = [dict(zip(statement.columns, row, strict=True)) for row in raw_rows]
        execution["source"] = "duckdb"
        execution["partitions"] = partitions
        execution["members"] = members.num_rows
        return (
            sanitize(rows, _aggregate_columns(statement.columns), self.limits),
            description + ", source duckdb",
        )

    def _run_duckdb(
        self, statement: compile_duckdb.DuckStatement, paths: list[Path], members: Any
    ) -> list[tuple[Any, ...]]:
        return compile_duckdb.run(
            statement,
            compile_duckdb.parts_dataset(paths),
            members,
            self.limits,
            self.limits.query_timeout_seconds,
        )

    def warm_cache(self) -> dict[str, Any]:
        """Fill the part cache with the environment's active parts, newest months first.

        Bounded by the cache size and ``warm_cache_seconds``; parts beyond the cache budget are
        skipped rather than evicting what was just warmed. Never raises for an empty database.
        """
        started = time.monotonic()
        if self.cache is None:
            return {"skipped": "no part cache configured"}
        try:
            environment = self.catalogue.environment()
        except QueryError as error:
            if error.code == "coverage_missing":
                return {"skipped": "no ingestion environment"}
            raise
        # Newest months first: slot keys carry the month in their third segment.
        parts = sorted(
            self.catalogue.active_parts(environment.id),
            key=lambda record: record.logical_key.split("/")[2],
            reverse=True,
        )
        selected: list[tuple[str, str, int]] = []
        budget = self.limits.object_cache_bytes
        for part in parts:
            if part.byte_count > budget:
                continue
            budget -= part.byte_count
            selected.append((part.key, part.sha256, part.byte_count))
        fill = self.cache.fill(
            selected,
            workers=self.limits.object_fetch_workers,
            deadline_seconds=self.limits.warm_cache_seconds,
        )
        record = {
            "environment": environment.name,
            "parts": len(parts),
            "warmed": len(selected),
            "skipped_over_budget": len(parts) - len(selected),
            "fetched": fill.fetched,
            "fetched_bytes": fill.fetched_bytes,
            "reused": fill.reused,
            "seconds": round(time.monotonic() - started, 1),
        }
        return record  # the API logs one warm_cache record per start-up

    @staticmethod
    def _aggregate_names(plan: QueryPlan) -> list[str]:
        assert isinstance(plan.operation, AggregateOperation)
        names: list[str] = [str(key) for key in plan.operation.group_by]
        for variable in plan.ordered_variables:
            for metric in plan.operation.metrics:
                names.append(f"{variable}_{metric}")
        return names
