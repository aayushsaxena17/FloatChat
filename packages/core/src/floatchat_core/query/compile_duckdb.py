"""DuckDB compiler and runner (ADR-0058): bounded, external access disabled, manifest semi-join.

The statement is a fixed template over two registered relations: ``parts`` (a pyarrow dataset
of the verified local part files, read by pyarrow with projection pushdown) and ``members``
(the profiles the PostgreSQL side selected, intersected with the slot membership manifests).
DuckDB never opens a path or a network endpoint.
"""

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.dataset as ds

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
            f"SELECT {', '.join(selects)} FROM {joined} WHERE {' AND '.join(where)}"
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
        f"SELECT {', '.join(outer_selects)} FROM ({inner}) per_profile{group}{order} "
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


def parts_dataset(paths: Sequence[Path]) -> ds.Dataset:
    return ds.dataset([str(path) for path in paths], format="parquet")


def run(
    statement: DuckStatement,
    parts: ds.Dataset,
    members: pa.Table,
    limits: QueryLimits,
    timeout_seconds: float,
) -> list[tuple[Any, ...]]:
    """Execute under a bounded, locked configuration with an interrupt deadline."""
    connection = duckdb.connect(
        database=":memory:",
        config={
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "memory_limit": f"{limits.duckdb_memory_mib}MiB",
            "threads": str(limits.duckdb_threads),
        },
    )
    timer = threading.Timer(max(0.05, timeout_seconds), connection.interrupt)
    try:
        connection.execute("SET lock_configuration = true")
        connection.register("parts", parts)
        connection.register("members", members)
        timer.start()
        try:
            return connection.execute(statement.sql, dict(statement.parameters)).fetchall()
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
        connection.close()
