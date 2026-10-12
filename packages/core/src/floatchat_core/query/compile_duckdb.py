"""DuckDB compiler and engine (ADR-0058, amended by ADR-0066): bounded, locked, manifest semi-join.

The statement is a fixed template over ``parts`` and ``members``. ``parts`` is DuckDB's own
Parquet reader over the verified local part files (``read_parquet`` with the file list bound as a
parameter, so DuckDB reads row groups in parallel and pushes the projection down); ``members`` is
the profiles the PostgreSQL side selected, intersected with the slot membership manifests.

One :class:`DuckEngine` per service holds a long-lived in-memory database configured once and
locked: only the part-cache directory is readable, external access and extension loading are off,
and the configuration cannot change afterwards. Each execution runs on its own cursor with its own
interrupt deadline, and a semaphore bounds how many run at once so the shared memory limit holds.
"""

import os
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from .errors import QueryError
from .limits import QueryLimits
from .plan import AggregateOperation, QueryPlan
from .policy import duck_value

PARTS_COLUMNS = (
    "profile_id",
    "profile_hash",
    "pressure",
    "pressure_adjusted",
    "pressure_qc",
    "pressure_adjusted_qc",
    "pressure_data_mode",
    "temperature",
    "temperature_adjusted",
    "temperature_qc",
    "temperature_adjusted_qc",
    "temperature_data_mode",
    "salinity",
    "salinity_adjusted",
    "salinity_qc",
    "salinity_adjusted_qc",
    "salinity_data_mode",
)
MEMBERS_SCHEMA = pa.schema(
    [
        pa.field("profile_id", pa.string(), nullable=False),
        pa.field("profile_hash", pa.string(), nullable=False),
        pa.field("platform_number", pa.string(), nullable=False),
        # Naive UTC: no ICU time-zone extension is needed for the month and day keys.
        pa.field("observed_at", pa.timestamp("us"), nullable=False),
    ]
)


@dataclass(frozen=True)
class DuckStatement:
    sql: str
    parameters: dict[str, Any]
    columns: tuple[str, ...]


def _metric(name: str, value: str) -> str:
    return {
        "mean": f"avg({value})",
        "count": f"count({value})",
        "min": f"min({value})",
        "max": f"max({value})",
        "stddev": f"stddev_samp({value})",
        "median": f"quantile_cont({value}, 0.5)",
    }[name]


def _key(key: str, policy: str) -> str:
    if key == "month":
        return "strftime(m.observed_at, '%Y-%m')"
    if key == "day":
        return "strftime(m.observed_at, '%Y-%m-%d')"
    if key == "profile":
        return "m.profile_id"
    if key == "float":
        return "m.platform_number"
    if key == "depth_bin":
        return f"floor(({duck_value('pressure', policy)}) / $depth_bin_size) * $depth_bin_size"
    if key == "region":
        return "$region_label"
    raise ValueError("unknown group key")


def aggregate_statement(plan: QueryPlan, *, label: str, max_rows: int) -> DuckStatement:
    """Fixed-template aggregate over ``parts`` and ``members`` with named parameters."""
    assert isinstance(plan.operation, AggregateOperation)
    operation = plan.operation
    policy = plan.qc_policy
    parameters: dict[str, Any] = {"row_limit": max_rows + 1}
    keys = list(operation.group_by)
    key_sql = {key: _key(key, policy) for key in keys}
    if "depth_bin" in keys:
        parameters["depth_bin_size"] = operation.depth_bin_size
    if "region" in keys:
        parameters["region_label"] = label
    where = ["m.profile_id IS NOT NULL"]
    if plan.depth_dbar is not None:
        where.append(f"({duck_value('pressure', policy)}) BETWEEN $depth_min AND $depth_max")
        parameters["depth_min"] = plan.depth_dbar.min
        parameters["depth_max"] = plan.depth_dbar.max
    joined = (
        "parts p JOIN members m ON p.profile_id = m.profile_id AND p.profile_hash = m.profile_hash"
    )
    # The engine binds $parts_files to the verified cache paths (DuckEngine.run).
    parts_cte = (
        f"WITH parts AS (SELECT {', '.join(PARTS_COLUMNS)} FROM read_parquet($parts_files)) "
    )
    variables = list(plan.ordered_variables)
    columns: list[str] = list(keys)
    if operation.unit == "measurement":
        selects = [f"{key_sql[key]} AS {key}" for key in keys]
        for variable in variables:
            value = duck_value(variable, policy)
            for metric in operation.metrics:
                selects.append(f"{_metric(metric, value)} AS {variable}_{metric}")
                columns.append(f"{variable}_{metric}")
        grouped = [key for key in keys if key != "region"]  # a constant label is not grouped
        group = f" GROUP BY {', '.join(key_sql[key] for key in grouped)}" if grouped else ""
        order = f" ORDER BY {', '.join(grouped)}" if grouped else ""
        sql = (
            f"{parts_cte}SELECT {', '.join(selects)} FROM {joined} WHERE {' AND '.join(where)}"
            f"{group}{order} LIMIT $row_limit"
        )
        return DuckStatement(sql, parameters, tuple(columns))
    inner_selects = ["m.profile_id AS profile_id"]
    inner_selects += [f"{key_sql[key]} AS key_{key}" for key in keys]
    inner_selects += [
        f"avg({duck_value(variable, policy)}) AS {variable}_value" for variable in variables
    ]
    inner_group = ", ".join(["m.profile_id", *[key_sql[key] for key in keys if key != "region"]])
    inner = (
        f"SELECT {', '.join(inner_selects)} FROM {joined} WHERE {' AND '.join(where)} "
        f"GROUP BY {inner_group}"
    )
    outer_selects = [f"key_{key} AS {key}" for key in keys]
    for variable in variables:
        for metric in operation.metrics:
            outer_selects.append(f"{_metric(metric, variable + '_value')} AS {variable}_{metric}")
            columns.append(f"{variable}_{metric}")
    group = f" GROUP BY {', '.join('key_' + key for key in keys)}" if keys else ""
    order = f" ORDER BY {', '.join('key_' + key for key in keys)}" if keys else ""
    sql = (
        f"{parts_cte}SELECT {', '.join(outer_selects)} FROM ({inner}) per_profile{group}{order} "
        "LIMIT $row_limit"
    )
    return DuckStatement(sql, parameters, tuple(columns))


def members_table(rows: Sequence[dict[str, Any]], manifests: dict[str, list[Any]]) -> pa.Table:
    """Selected profiles intersected with the slot manifests (contract section 7.2)."""
    allowed = {
        (str(entry["profile_id"]), str(entry["hash"]))
        for manifest in manifests.values()
        for entry in manifest
    }
    kept = [row for row in rows if (row["profile_id"], row["profile_hash"]) in allowed]
    return pa.Table.from_pydict(
        {
            "profile_id": [row["profile_id"] for row in kept],
            "profile_hash": [row["profile_hash"] for row in kept],
            "platform_number": [row["platform_number"] for row in kept],
            "observed_at": [
                row["observed_at"].astimezone(UTC).replace(tzinfo=None) for row in kept
            ],
        },
        schema=MEMBERS_SCHEMA,
    )


def members_from_columns(
    names: Sequence[str], rows: Sequence[tuple[Any, ...]], manifests: dict[str, list[Any]]
) -> pa.Table:
    """``members_table`` over plain tuples (the PostgreSQL selection fetched without mapping)."""
    index = {name: position for position, name in enumerate(names)}
    allowed = {
        (str(entry["profile_id"]), str(entry["hash"]))
        for manifest in manifests.values()
        for entry in manifest
    }
    pid, digest = index["profile_id"], index["profile_hash"]
    kept = [row for row in rows if (row[pid], row[digest]) in allowed]
    platform, observed = index["platform_number"], index["observed_at"]
    return pa.Table.from_pydict(
        {
            "profile_id": [row[pid] for row in kept],
            "profile_hash": [row[digest] for row in kept],
            "platform_number": [row[platform] for row in kept],
            "observed_at": [row[observed].astimezone(UTC).replace(tzinfo=None) for row in kept],
        },
        schema=MEMBERS_SCHEMA,
    )


PART_NAME = re.compile(r"^[0-9a-f]{64}\.parquet$")


def default_threads() -> int:
    """CPUs visible to the process (inside a container: the host's, not the cgroup quota)."""
    return max(1, os.cpu_count() or 1)


class DuckEngine:
    """A long-lived, locked DuckDB database reading only the verified part cache (ADR-0066)."""

    def __init__(self, cache_directory: Path, limits: QueryLimits) -> None:
        self.directory = cache_directory.resolve()
        self.limits = limits
        threads = limits.duckdb_threads or default_threads()
        self._connection = duckdb.connect(
            database=":memory:",
            config={
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "memory_limit": f"{limits.duckdb_memory_mib}MiB",
                "threads": str(threads),
            },
        )
        # allowed_directories can only be set once the database is running, and must be set
        # before external access is switched off; the lock then freezes every setting.
        literal = str(self.directory).replace("'", "''") + "/"
        self._connection.execute(f"SET allowed_directories = ['{literal}']")
        self._connection.execute("SET parquet_metadata_cache = true")
        self._connection.execute("SET enable_external_access = false")
        self._connection.execute("SET lock_configuration = true")
        self.threads = threads
        self._slots = threading.BoundedSemaphore(limits.duckdb_concurrency)
        self._closed = False

    def verified_files(self, paths: Sequence[Path]) -> list[str]:
        """Only content-addressed files directly inside the cache directory reach DuckDB."""
        files = []
        for path in paths:
            resolved = Path(path).resolve()
            if resolved.parent != self.directory or not PART_NAME.match(resolved.name):
                raise QueryError("internal_error", message="A part path is outside the cache.")
            files.append(str(resolved))
        return files

    def run(
        self,
        statement: DuckStatement,
        paths: Sequence[Path],
        members: pa.Table,
        timeout_seconds: float,
    ) -> list[tuple[Any, ...]]:
        """Execute on a fresh cursor under the interrupt deadline and the concurrency bound."""
        parameters = dict(statement.parameters)
        if "$parts_files" in statement.sql:
            parameters["parts_files"] = self.verified_files(paths)
        deadline = time.monotonic() + max(0.05, timeout_seconds)
        # Waiting for a slot counts against the same deadline as the execution itself.
        if not self._slots.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise QueryError("statement_timeout")
        try:
            cursor = self._connection.cursor()
            timer = threading.Timer(max(0.05, deadline - time.monotonic()), cursor.interrupt)
            try:
                cursor.register("members", members)
                timer.start()
                return cursor.execute(statement.sql, parameters).fetchall()
            except duckdb.InterruptException:
                raise QueryError("statement_timeout") from None
            except duckdb.OutOfMemoryException:
                raise QueryError(
                    "cost_over_budget", message="The scan exceeded its memory budget."
                ) from None
            except duckdb.Error:
                raise QueryError("execution_failed") from None
            finally:
                timer.cancel()
                cursor.close()
        finally:
            self._slots.release()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()
