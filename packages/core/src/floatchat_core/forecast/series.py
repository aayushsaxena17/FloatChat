"""The regular monthly series behind a forecast and its snapshot (ADR-0083).

The builder runs the query engine's own aggregate template (``group_by month``, ``unit
profile``) with DuckDB in the worker, one calendar year per execution, over the verified parts
of the definition's months and tiles, with members from PostgreSQL. The snapshot records the
dataset version, every part read, the month values and counts and the missing-data treatment.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..ingestion.planning import GEOMETRY_VERSION, MAPPINGS, Interval, Tile, shift_months
from ..query import compile_duckdb, compile_sql
from ..query.cache import PartCache
from ..query.catalogue import Coverage, EnvironmentInfo, months_of, translate_error
from ..query.compile_duckdb import PART_NAME
from ..query.errors import QueryError
from ..query.geography import ResolvedGeography
from ..query.plan import QueryPlan
from .model import SNAPSHOT_SCHEMA, Definition, ForecastLimits


@dataclass(frozen=True)
class SeriesSnapshot:
    """``series-snapshot-v1``: everything a model needs to be retrained exactly."""

    id: str
    definition: dict[str, Any]
    dataset_version: dict[str, Any]
    months: list[str]
    values: list[float | None]
    counts: list[int]
    partitions: list[dict[str, str]]
    versions: dict[str, Any]
    built_at: str
    application_commit: str
    coverage: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "id": self.id,
            "definition": self.definition,
            "dataset_version": self.dataset_version,
            "months": self.months,
            "values": self.values,
            "counts": self.counts,
            "partitions": self.partitions,
            "versions": self.versions,
            "coverage": self.coverage,
            "built_at": self.built_at,
            "application_commit": self.application_commit,
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "SeriesSnapshot":
        return cls(
            id=str(document["id"]),
            definition=dict(document["definition"]),
            dataset_version=dict(document.get("dataset_version", {})),
            months=list(document["months"]),
            values=[None if v is None else float(v) for v in document["values"]],
            counts=[int(c) for c in document["counts"]],
            partitions=list(document.get("partitions", [])),
            versions=dict(document.get("versions", {})),
            built_at=str(document.get("built_at", "")),
            application_commit=str(document.get("application_commit", "unknown")),
            coverage=dict(document.get("coverage", {})),
        )


@dataclass(frozen=True)
class RegularSeries:
    """The series after the missing policy: no gaps, trimmed, with the filled months flagged."""

    months: list[str]
    values: list[float]
    filled: list[bool]
    policy: dict[str, Any]


class Refusal(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def apply_missing_policy(
    months: list[str], values: list[float | None], counts: list[int], limits: ForecastLimits
) -> RegularSeries:
    """Trim leading and trailing gaps; interpolate short interior gaps; refuse beyond policy."""
    present = [index for index, value in enumerate(values) if value is not None]
    if not present:
        raise Refusal("history_too_short", "No month has enough profiles for a value.")
    first, last = present[0], present[-1]
    window_months = months[first : last + 1]
    window_values = values[first : last + 1]
    missing = [index for index, value in enumerate(window_values) if value is None]
    total = len(window_values)
    if total < limits.min_months:
        raise Refusal(
            "history_too_short",
            f"Only {total} regular months with data; at least {limits.min_months} are needed.",
        )
    longest = 0
    run = 0
    for value in window_values:
        run = run + 1 if value is None else 0
        longest = max(longest, run)
    fraction = len(missing) / total
    if fraction > limits.max_missing_fraction or longest > limits.max_gap_months:
        raise Refusal(
            "missingness_exceeds_policy",
            f"{len(missing)} of {total} months ({fraction:.0%}) are missing and the longest "
            f"gap is {longest} months; the policy allows {limits.max_missing_fraction:.0%} "
            f"and gaps of {limits.max_gap_months}.",
        )
    filled: list[float] = []
    flags: list[bool] = []
    for index, value in enumerate(window_values):
        if value is not None:
            filled.append(float(value))
            flags.append(False)
            continue
        before = next(i for i in range(index - 1, -1, -1) if window_values[i] is not None)
        after = next(i for i in range(index + 1, total) if window_values[i] is not None)
        left, right = float(window_values[before]), float(window_values[after])  # type: ignore[arg-type]
        weight = (index - before) / (after - before)
        filled.append(left + (right - left) * weight)
        flags.append(True)
    policy = {
        "rule": "min_profiles per month; trim leading and trailing gaps; linear interpolation "
        "of interior gaps",
        "max_missing_fraction": limits.max_missing_fraction,
        "max_gap_months": limits.max_gap_months,
        "months_total": total,
        "months_missing": len(missing),
        "longest_gap": longest,
        "trimmed_leading": first,
        "trimmed_trailing": len(values) - 1 - last,
        "filled_months": [window_months[i] for i in missing],
    }
    return RegularSeries(window_months, filled, flags, policy)


def check_eligibility(series: RegularSeries, horizon: int, limits: ForecastLimits) -> None:
    values = series.values
    if len(values) < limits.min_months:
        raise Refusal("history_too_short", f"{len(values)} months; {limits.min_months} needed.")
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    if variance == 0 or variance**0.5 <= 1e-6 * max(1.0, abs(mean)):
        raise Refusal("series_constant", "The series has no variance to model.")
    if horizon > len(values) / 4:
        raise Refusal(
            "horizon_disproportionate",
            f"A horizon of {horizon} months is more than a quarter of {len(values)} months.",
        )


class SeriesBuilder:
    """Builds the monthly profile-balanced series over the committed parts."""

    def __init__(
        self,
        *,
        query_engine: Engine,
        cache: PartCache,
        limits: ForecastLimits,
        application_commit: str = "unknown",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.query_engine = query_engine
        self.cache = cache
        self.limits = limits
        self.application_commit = application_commit
        self.clock = clock

    def _connection(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(
            database=":memory:",
            config={
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "memory_limit": "256MiB",
                "threads": "2",
            },
        )
        cache = str(self.cache.directory.resolve()).replace("'", "''") + "/"
        connection.execute(f"SET allowed_directories = ['{cache}']")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        return connection

    def _members(
        self, plan: QueryPlan, geography: ResolvedGeography, coverage: Coverage
    ) -> pa.Table:
        statement = compile_sql.profile_slot_statement(
            plan, geography, [slot.logical_key for slot in coverage.covered]
        )
        try:
            with self.query_engine.connect() as connection:
                result = connection.execute(statement)
                names = list(result.keys())
                rows = [tuple(row) for row in result.all()]
        except SQLAlchemyError as error:
            raise translate_error(error) from None
        return compile_duckdb.members_from_columns(names, rows, coverage.manifests)

    def build(
        self,
        definition: Definition,
        geography: ResolvedGeography,
        environment: EnvironmentInfo,
        coverage_for: Callable[[Interval], Coverage],
    ) -> SeriesSnapshot:
        """One execution per calendar year: members, verified parts, the aggregate template."""
        months = months_of(Interval(definition.series_start, definition.series_end))
        values: dict[str, float | None] = {f"{m:%Y-%m}": None for m in months}
        counts: dict[str, int] = {f"{m:%Y-%m}": 0 for m in months}
        partitions: list[dict[str, str]] = []
        coverage_summary = {"slots_total": 0, "slots_covered": 0, "slots_missing": 0}
        cursor = definition.series_start
        connection = self._connection()
        try:
            while cursor < definition.series_end:
                year_end = min(
                    shift_months(cursor.replace(month=1, day=1), 12), definition.series_end
                )
                interval = Interval(cursor, year_end)
                plan = QueryPlan.model_validate(
                    {
                        "time_range": {"start": interval.start, "end": interval.end},
                        "geography": {"kind": "named_region", "value": definition.region},
                        "depth_dbar": {"min": definition.depth_min, "max": definition.depth_max},
                        "variables": [definition.variable],
                        "qc_policy": "science_ready",
                        "operation": {
                            "kind": "aggregate",
                            "group_by": ["month"],
                            "metrics": ["mean", "count"],
                            "unit": "profile",
                        },
                        "presentation": {"kind": "table"},
                    }
                )
                coverage = coverage_for(interval)
                coverage_summary["slots_total"] += len(coverage.slots)
                coverage_summary["slots_covered"] += len(coverage.covered)
                coverage_summary["slots_missing"] += len(coverage.missing)
                parts = [part for slot in coverage.covered for part in slot.parts]
                if parts:
                    fill = self.cache.fill(
                        [(part.key, part.sha256, part.byte_count) for part in parts],
                        workers=4,
                        deadline_seconds=1800,
                    )
                    partitions.extend(
                        {"id": str(part.partition_id), "sha256": part.sha256} for part in parts
                    )
                    members = self._members(plan, geography, coverage)
                    statement = compile_duckdb.aggregate_statement(
                        plan, label=geography.label, max_rows=100_000
                    )
                    parameters = dict(statement.parameters)
                    parameters["parts_files"] = self._verified(fill.paths)
                    try:
                        connection.register("members", members)
                        rows = connection.execute(statement.sql, parameters).fetchall()
                    except duckdb.Error as error:
                        raise QueryError(
                            "execution_failed", message=f"DuckDB: {type(error).__name__}"
                        ) from None
                    for row in rows:
                        record = dict(zip(statement.columns, row, strict=True))
                        month = str(record["month"])
                        if month not in values:
                            continue
                        count = int(record.get(f"{definition.variable}_count") or 0)
                        mean = record.get(f"{definition.variable}_mean")
                        counts[month] = count
                        values[month] = (
                            float(mean)
                            if mean is not None and count >= definition.min_profiles
                            else None
                        )
                cursor = year_end
        finally:
            connection.close()
        ordered = list(values)
        snapshot_payload = {
            "definition": definition.as_dict(),
            "dataset_version": environment.describe(),
            "months": ordered,
            "values": [values[m] for m in ordered],
            "counts": [counts[m] for m in ordered],
            "partitions": sorted(partitions, key=lambda p: p["sha256"]),
        }
        digest = hashlib.sha256(
            json.dumps(snapshot_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        return SeriesSnapshot(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, digest)),
            definition=definition.as_dict(),
            dataset_version=environment.describe(),
            months=ordered,
            values=[values[m] for m in ordered],
            counts=[counts[m] for m in ordered],
            partitions=sorted(partitions, key=lambda p: p["sha256"]),
            versions={
                "mapping": MAPPINGS["argovis"],
                "geometry": GEOMETRY_VERSION,
                "qc_policy": "qc-policy-v1/science_ready",
                "region": geography.describe(),
            },
            coverage=coverage_summary,
            built_at=self.clock().isoformat().replace("+00:00", "Z"),
            application_commit=self.application_commit,
        )

    def _verified(self, paths: list[Path]) -> list[str]:
        files = []
        for path in paths:
            resolved = Path(path).resolve()
            if resolved.parent != self.cache.directory.resolve() or not PART_NAME.match(
                resolved.name
            ):
                raise QueryError("internal_error", message="A part path is outside the cache.")
            files.append(str(resolved))
        return files


def tiles_of(cells: list[list[int]]) -> tuple[Tile, ...]:
    return tuple(Tile(int(west), int(south)) for west, south in cells)
