"""Stage 2 latency report: p50/p95 of the query API against the dev project (plan section 9, W7).

Posts a fixed matrix of twenty valid ``stage2-plan-v1`` documents to ``POST /v1/query`` (ten per
route group, chosen by estimated cost so the router selects the group's route) and times four
metadata routes. Every query is measured once cold (the first call after the optional restart)
and then ``--runs`` times warm after ``--warmup`` discarded calls. The route is asserted from
``execution.source``. Writes ``reports/query_latency_<date>.json`` (all samples) and ``.md``.

    uv run --all-packages --frozen python scripts/query_latency.py \\
        --base-url http://127.0.0.1:8000 --runs 20 \\
        --dataset-report reports/stage2-dataset-<session>.json

Every number in the report comes from a measured sample. Only urllib is used; the requests carry
no credentials. Exit status: 0 when every request succeeded on its expected route, 2 when any
request failed or ran on another route (the files are still written), 1 when the run could not
start (unreadable dataset report, failed restart command, API never became live).
"""

import argparse
import http.client
import json
import math
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

REQUEST_TIMEOUT_S = 60.0
READY_TIMEOUT_S = 120.0
# PRD section 3.1: "Metadata/API p95 latency under 2 seconds", "Cached aggregate-query p95
# latency under 5 seconds". Both are applied to the warm, client-observed wall time.
METADATA_OBJECTIVE_MS = 2000.0
AGGREGATE_OBJECTIVE_MS = 5000.0

POSTGRESQL = "postgresql"
DUCKDB = "duckdb"
METADATA = "metadata"
TABLES = (
    (POSTGRESQL, "PostgreSQL route (profile listings, nearest, small aggregates)"),
    (DUCKDB, "DuckDB route (aggregates up to the whole-envelope quarter)"),
    (METADATA, "Metadata routes"),
)
OBJECTIVES = {
    POSTGRESQL: AGGREGATE_OBJECTIVE_MS,
    DUCKDB: AGGREGATE_OBJECTIVE_MS,
    METADATA: METADATA_OBJECTIVE_MS,
}

METHODOLOGY = (
    "One optional restart command, then a cold pass of one call per query plan in matrix order "
    "and one call per metadata route, then for each plan and route --warmup discarded calls "
    "followed by --runs recorded warm calls. Wall time is time.perf_counter around the HTTP "
    "request and body read (loopback, no proxy); server time is execution.elapsed_ms. p50 and "
    "p95 are nearest-rank over the sorted warm samples. A call that fails ends the warm loop "
    "of its plan and marks the row. Later cold calls may benefit from object-cache fills made "
    "by earlier plans of the same pass; the on-disk object cache is emptied only if the restart "
    "command does so."
)

# Matrix constants. The data is Jan-Mar 2025, Indian Ocean (acceptance reference 2025-04-01).
JAN = ("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z")
FEB = ("2025-02-01T00:00:00Z", "2025-03-01T00:00:00Z")
MAR = ("2025-03-01T00:00:00Z", "2025-04-01T00:00:00Z")
JAN_FEB = (JAN[0], FEB[1])
QUARTER = (JAN[0], MAR[1])
BOTH = ("temperature", "salinity")
METRICS = ("mean", "count", "min", "max", "median")

METADATA_ROUTES = (
    ("GET /v1/catalog/parameters", "/v1/catalog/parameters"),
    ("GET /v1/catalog/coverage?region=Arabian Sea", "/v1/catalog/coverage?region=Arabian%20Sea"),
    ("GET /v1/floats?limit=100", "/v1/floats?limit=100"),
    (
        "GET /v1/profiles?region=Arabian Sea&limit=100",
        "/v1/profiles?region=Arabian%20Sea&limit=100",
    ),
)


class Failure(Exception):
    """The run could not start or continue; reported on stderr with exit status 1."""


def percentile(samples: Sequence[float], p: float) -> float | None:
    """Nearest-rank percentile: the smallest sample with at least p percent at or below it."""
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    if not samples:
        return None
    ordered = sorted(samples)
    # The rounding guards the ceiling against float noise such as 0.95 * 20 = 18.999999999999996.
    rank = max(1, math.ceil(round(p * len(ordered) / 100, 9)))
    return ordered[rank - 1]


def _geography_region(name: str) -> dict[str, Any]:
    return {"kind": "named_region", "value": name}


def _geography_bbox(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return {"kind": "bbox", "west": west, "south": south, "east": east, "north": north}


def _plan(
    geography: dict[str, Any],
    operation: dict[str, Any],
    span: tuple[str, str],
    *,
    depth: tuple[float, float] | None = None,
    variables: Sequence[str] = BOTH,
    qc_policy: str = "science_ready",
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "dataset": "core",
        "time_range": {"start": span[0], "end": span[1]},
        "geography": geography,
        "variables": list(variables),
        "qc_policy": qc_policy,
        "operation": operation,
        "presentation": {"kind": "table"},
    }
    if depth is not None:
        plan["depth_dbar"] = {"min": depth[0], "max": depth[1]}
    return plan


def _profiles(limit: int = 100) -> dict[str, Any]:
    return {"kind": "profiles", "limit": limit}


def _aggregate(
    group_by: Sequence[str],
    *,
    unit: str = "profile",
    metrics: Sequence[str] = METRICS,
    depth_bin_size: int | None = None,
) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "kind": "aggregate",
        "group_by": list(group_by),
        "metrics": list(metrics),
        "unit": unit,
    }
    if depth_bin_size is not None:
        operation["depth_bin_size"] = depth_bin_size
    return operation


def _nearest(
    label: str, longitude: float, latitude: float, radius_km: float, k: int, span: tuple[str, str]
) -> dict[str, Any]:
    geography = {
        "kind": "point_radius",
        "longitude": longitude,
        "latitude": latitude,
        "radius_km": radius_km,
    }
    operation = {
        "kind": "nearest",
        "longitude": longitude,
        "latitude": latitude,
        "radius_km": radius_km,
        "k": k,
    }
    return _query(POSTGRESQL, label, "nearest", _plan(geography, operation, span))


def _query(group: str, label: str, kind: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "group": group,
        "kind": kind,
        "expected_route": group,
        "plan": plan,
    }


def build_matrix() -> dict[str, list[dict[str, Any]]]:
    """The fixed measurement matrix: ``queries`` (10 + 10 plans) and ``metadata`` (4 routes).

    The router chooses by estimated levels (PostgreSQL up to 1,000,000, DuckDB up to 5,000,000),
    so the PostgreSQL group stays within one or two small areas and months while the DuckDB group
    covers the whole 10-degree-tile envelope, which holds about 4.1 million levels in the
    acceptance data. An aggregate over more than 31 days needs a month key (plan section 4.2),
    so every DuckDB plan groups by month.
    """
    pg = POSTGRESQL
    queries = [
        _query(
            pg,
            "P01 profiles, Arabian Sea, Jan",
            "profiles",
            _plan(_geography_region("Arabian Sea"), _profiles(), JAN),
        ),
        _query(
            pg,
            "P02 profiles, Bay of Bengal, Feb, 0-200 dbar",
            "profiles",
            _plan(_geography_region("Bay of Bengal"), _profiles(), FEB, depth=(0, 200)),
        ),
        _query(
            pg,
            "P03 profiles, bbox 50E-75E 10S-20N, quarter, temperature",
            "profiles",
            _plan(
                _geography_bbox(50, -10, 75, 20),
                _profiles(),
                QUARTER,
                variables=("temperature",),
            ),
        ),
        _query(
            pg,
            "P04 profiles, Southern Indian Ocean, Mar, 500-1000 dbar",
            "profiles",
            _plan(
                _geography_region("Southern Indian Ocean"),
                _profiles(),
                MAR,
                depth=(500, 1000),
            ),
        ),
        _nearest("P05 nearest 10 within 500 km of 65E 15N, quarter", 65.0, 15.0, 500, 10, QUARTER),
        _nearest(
            "P06 nearest 50 within 1000 km of 88E 10N, quarter", 88.0, 10.0, 1000, 50, QUARTER
        ),
        _nearest(
            "P07 nearest 100 within 2000 km of 75E 40S, quarter", 75.0, -40.0, 2000, 100, QUARTER
        ),
        _query(
            pg,
            "P08 aggregate, Laccadive Sea, Jan, by month",
            "aggregate",
            _plan(
                _geography_region("Laccadive Sea"),
                _aggregate(["month"], metrics=("mean", "count")),
                JAN,
            ),
        ),
        _query(
            pg,
            "P09 aggregate, bbox 60E-75E 5N-20N, Feb, by month",
            "aggregate",
            _plan(
                _geography_bbox(60, 5, 75, 20),
                _aggregate(["month"], metrics=("mean", "count", "min", "max")),
                FEB,
            ),
        ),
        _query(
            pg,
            "P10 aggregate, Andaman Sea, Mar, 0-500 dbar, by month",
            "aggregate",
            _plan(
                _geography_region("Andaman Sea"),
                _aggregate(["month"], metrics=("mean", "count", "median")),
                MAR,
                depth=(0, 500),
            ),
        ),
    ]
    whole = _geography_region("Indian Ocean")
    duckdb_plans: list[tuple[str, dict[str, Any]]] = [
        (
            "D01 Indian Ocean, Jan-Feb, by month, profile",
            _plan(whole, _aggregate(["month"]), JAN_FEB),
        ),
        (
            "D02 Indian Ocean, quarter, by month, profile",
            _plan(whole, _aggregate(["month"]), QUARTER),
        ),
        (
            "D03 Indian Ocean, quarter, by month, measurement",
            _plan(whole, _aggregate(["month"], unit="measurement"), QUARTER),
        ),
        (
            "D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile",
            _plan(
                whole,
                _aggregate(["month", "depth_bin"], depth_bin_size=100),
                QUARTER,
                depth=(0, 2000),
            ),
        ),
        (
            "D05 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, measurement",
            _plan(
                whole,
                _aggregate(["month", "depth_bin"], unit="measurement", depth_bin_size=100),
                QUARTER,
                depth=(0, 2000),
            ),
        ),
        (
            "D06 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, profile",
            _plan(
                whole,
                _aggregate(["month", "depth_bin"], depth_bin_size=50),
                QUARTER,
                depth=(0, 1000),
            ),
        ),
        (
            "D07 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, measurement",
            _plan(
                whole,
                _aggregate(["month", "depth_bin"], unit="measurement", depth_bin_size=50),
                QUARTER,
                depth=(0, 1000),
            ),
        ),
        (
            "D08 Indian Ocean, quarter, month+float, profile",
            _plan(whole, _aggregate(["month", "float"]), QUARTER),
        ),
        (
            "D09 Indian Ocean, quarter, month+float, measurement",
            _plan(whole, _aggregate(["month", "float"], unit="measurement"), QUARTER),
        ),
        (
            "D10 Indian Ocean, quarter, month+depth_bin 50, whole profile, temperature",
            _plan(
                whole,
                _aggregate(["month", "depth_bin"], depth_bin_size=50),
                QUARTER,
                variables=("temperature",),
            ),
        ),
    ]
    queries.extend(_query(DUCKDB, label, "aggregate", plan) for label, plan in duckdb_plans)
    metadata = [
        {"label": label, "group": METADATA, "kind": "metadata", "method": "GET", "path": path}
        for label, path in METADATA_ROUTES
    ]
    return {"queries": queries, "metadata": metadata}


@dataclass
class Call:
    """One HTTP exchange: status (None on a transport failure), wall time, parsed body, error."""

    status: int | None
    wall_ms: float
    body: dict[str, Any] | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class Client:
    """Minimal urllib client: no proxy, 60 s timeout, one ``X-Correlation-ID: latency-<n>`` each."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        # Loopback latency must not depend on a proxy picked up from the environment.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._counter = 0

    def request(
        self,
        method: str,
        path: str,
        document: dict[str, Any] | None = None,
        *,
        correlation: str | None = None,
    ) -> Call:
        if correlation is None:
            self._counter += 1
            correlation = f"latency-{self._counter}"
        headers = {"Accept": "application/json", "X-Correlation-ID": correlation}
        data = None
        if document is not None:
            data = json.dumps(document).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        status: int | None = None
        raw = b""
        error: str | None = None
        started = time.perf_counter()
        try:
            with self._opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as failure:
            status = failure.code
            try:
                raw = failure.read()
            except (OSError, http.client.HTTPException):
                raw = b""
            error = "http_error"
        except urllib.error.URLError as failure:
            error = "timeout" if isinstance(failure.reason, TimeoutError) else "connection_error"
        except TimeoutError:
            error = "timeout"
        except (OSError, http.client.HTTPException):
            error = "connection_error"
        wall_ms = (time.perf_counter() - started) * 1000
        body: dict[str, Any] | None = None
        if raw:
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                body = parsed
        if error == "http_error":
            # The stable envelope: {"error": {"code", "message", "details", "correlation_id"}}.
            code = _dig(body, "error", "code")
            error = code if isinstance(code, str) and code else f"http_{status}"
        elif error is None and body is None:
            error = "invalid_response"
        return Call(status, wall_ms, body, error)

    def query(self, plan: dict[str, Any]) -> Call:
        return self.request("POST", "/v1/query", plan)


def _dig(document: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def summarise(entry: dict[str, Any], cold: Call, warm: Sequence[Call]) -> dict[str, Any]:
    """One table row from the cold call and the recorded warm calls (failures included)."""
    calls = [cold, *warm]
    good = [call for call in calls if call.ok]
    warm_good = [call for call in warm if call.ok]
    failures = [call for call in calls if not call.ok]
    is_query = entry["kind"] != "metadata"
    routes = sorted(
        {
            source
            for call in good
            if isinstance(source := _dig(call.body, "execution", "source"), str)
        }
    )
    first = good[0].body if good else None
    server_all = [_number(_dig(call.body, "execution", "elapsed_ms")) for call in warm_good]
    server = [value for value in server_all if value is not None]
    warm_ms = [round(call.wall_ms, 3) for call in warm_good]
    cold_server = _number(_dig(cold.body, "execution", "elapsed_ms")) if cold.ok else None
    row: dict[str, Any] = {
        "label": entry["label"],
        "group": entry["group"],
        "kind": entry["kind"],
        "status": "ok" if not failures else failures[0].error,
        "http_status": failures[0].status if failures else cold.status,
        "failed_calls": len(failures),
        "error_codes": sorted({str(call.error) for call in failures}),
        "estimated_levels": _dig(first, "coverage", "estimated_levels") if is_query else None,
        "rows": _dig(first, "result", "row_count"),
        "partial": any(_dig(call.body, "partial") is True for call in good) if is_query else None,
        "cold_ms": round(cold.wall_ms, 3) if cold.ok else None,
        "cold_server_ms": cold_server,
        "warm_ms": warm_ms,
        "server_ms": server,
        "warm_p50_ms": percentile(warm_ms, 50),
        "warm_p95_ms": percentile(warm_ms, 95),
        "server_p50_ms": percentile(server, 50),
        "server_p95_ms": percentile(server, 95),
    }
    if is_query:
        row["expected_route"] = entry["expected_route"]
        row["actual_route"] = "+".join(routes) if routes else None
        row["route_ok"] = routes == [entry["expected_route"]]
        row["plan"] = entry["plan"]
    else:
        row["method"] = entry["method"]
        row["path"] = entry["path"]
    return row


def table_verdict(table: dict[str, Any]) -> dict[str, Any]:
    """Pass/fail of one table against its PRD section 3.1 objective (strictly under)."""
    objective = float(table["objective_ms"])
    problems: list[str] = []
    worst: float | None = None
    rows = table["rows"]
    if not rows:
        problems.append("no measurements")
    for row in rows:
        label = row["label"]
        p95 = row.get("warm_p95_ms")
        if p95 is not None:
            worst = p95 if worst is None else max(worst, p95)
        if row["status"] != "ok":
            problems.append(f"{label}: failed with {row['status']}")
        elif row.get("expected_route") is not None and not row.get("route_ok", False):
            problems.append(
                f"{label}: ran on {row.get('actual_route') or 'no route'}, "
                f"expected {row['expected_route']}"
            )
        elif p95 is None:
            problems.append(f"{label}: no warm samples")
        elif p95 >= objective:
            problems.append(f"{label}: warm p95 {p95:.1f} ms is not under {objective:.0f} ms")
    return {
        "pass": not problems,
        "objective_ms": objective,
        "worst_warm_p95_ms": worst,
        "problems": problems,
    }


def build_report(
    meta: dict[str, Any],
    query_rows: Sequence[dict[str, Any]],
    metadata_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The JSON document: header metadata plus the three tables with their verdicts."""
    by_group = {
        POSTGRESQL: [row for row in query_rows if row["group"] == POSTGRESQL],
        DUCKDB: [row for row in query_rows if row["group"] == DUCKDB],
        METADATA: list(metadata_rows),
    }
    tables = []
    for identifier, title in TABLES:
        table = {
            "id": identifier,
            "title": title,
            "objective_ms": OBJECTIVES[identifier],
            "rows": by_group[identifier],
        }
        table["verdict"] = table_verdict(table)
        tables.append(table)
    report = {"kind": "stage2_query_latency", **meta, "tables": tables}
    report["failures"] = failure_count(report)
    return report


def failure_count(report: dict[str, Any]) -> int:
    """Rows that failed outright or ran on another route than their group's expected one."""
    count = 0
    for table in report["tables"]:
        for row in table["rows"]:
            if row["status"] != "ok" or (
                row.get("expected_route") is not None and not row.get("route_ok", False)
            ):
                count += 1
    return count


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _count(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "-"


def _route_cell(row: dict[str, Any]) -> str:
    expected = row.get("expected_route")
    if expected is None:
        return METADATA
    actual = row.get("actual_route")
    if row.get("route_ok"):
        return str(actual)
    return f"**{actual or '-'}** (expected {expected})"


def _status_cell(row: dict[str, Any]) -> str:
    if row["status"] != "ok":
        http = f" HTTP {row['http_status']}" if row.get("http_status") else ""
        return f"**{row['status']}**{http}"
    if row.get("expected_route") is not None and not row.get("route_ok"):
        return "**route mismatch**"
    return "ok (partial)" if row.get("partial") else "ok"


def _table_markdown(table: dict[str, Any]) -> list[str]:
    verdict = table_verdict(table)
    lines = [
        f"## {table['title']}",
        "",
        "| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms "
        "| server p50 ms | server p95 ms | status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in table["rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(_route_cell(row)),
                    _cell(row["label"]),
                    _count(row.get("estimated_levels")),
                    _count(row.get("rows")),
                    _ms(row.get("cold_ms")),
                    _ms(row.get("warm_p50_ms")),
                    _ms(row.get("warm_p95_ms")),
                    _ms(row.get("server_p50_ms")),
                    _ms(row.get("server_p95_ms")),
                    _cell(_status_cell(row)),
                ]
            )
            + " |"
        )
    worst = verdict["worst_warm_p95_ms"]
    lines += [
        "",
        f"Objective (PRD section 3.1): warm p95 under {verdict['objective_ms']:.0f} ms. "
        f"Worst warm p95: {_ms(worst)} ms. **{'PASS' if verdict['pass'] else 'FAIL'}**",
    ]
    for problem in verdict["problems"]:
        lines.append(f"- {_cell(problem)}")
    lines.append("")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """The Markdown report; verdicts are recomputed from the rows, never read from the JSON."""
    dataset = report.get("dataset")
    limits = report.get("limits")
    lines = [
        f"# Stage 2 query latency report, {report['date']}",
        "",
        f"- Commit: `{report['git_head']}`"
        + (" (uncommitted changes)" if report.get("git_dirty") else ""),
        f"- Base URL: {report['base_url']}",
        f"- Runs per plan: {report['runs']} warm after {report['warmup']} discarded; "
        "one cold call per plan"
        + (" after the restart command" if report.get("restart_command") else " (no restart)"),
        f"- Host: {report['host']}, {report['cpu_count']} CPUs",
    ]
    if dataset:
        lines.append(
            f"- Dataset: source session `{dataset.get('session')}`, "
            f"digest (dump SHA-256) `{dataset.get('digest')}`"
        )
    else:
        lines.append("- Dataset: no dataset report given")
    if isinstance(limits, dict) and limits:
        lines.append(
            "- API limits (`/v1/catalog/parameters`): "
            + ", ".join(f"{key}={limits[key]}" for key in sorted(limits))
        )
    else:
        lines.append("- API limits: not available (parameters request failed)")
    lines += ["", f"Method: {report.get('methodology', METHODOLOGY)}", ""]
    verdicts = []
    for table in report["tables"]:
        lines += _table_markdown(table)
        verdicts.append((table["title"], table_verdict(table)))
    lines += ["## Comparison with PRD section 3.1", ""]
    lines.append("| table | objective | worst warm p95 ms | result |")
    lines.append("|---|---|---:|---|")
    for title, verdict in verdicts:
        lines.append(
            f"| {_cell(title)} | p95 under {verdict['objective_ms']:.0f} ms "
            f"| {_ms(verdict['worst_warm_p95_ms'])} | {'PASS' if verdict['pass'] else 'FAIL'} |"
        )
    lines += [
        "",
        "Metadata objective: Metadata/API p95 under 2 seconds. Aggregate objective: cached "
        "aggregate-query p95 under 5 seconds, applied to every row of both query tables.",
        "",
    ]
    return "\n".join(lines)


def git_state() -> tuple[str, bool]:
    """Short HEAD and whether the working tree has uncommitted changes."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown", False
    return head or "unknown", bool(dirty)


def load_dataset_report(path: Path) -> dict[str, Any]:
    """Session and digest from a ``reports/stage2-dataset-*.json`` written by stage2_dataset.py."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise Failure(f"cannot read dataset report {path}: {error}") from None
    if not isinstance(document, dict):
        raise Failure(f"dataset report {path} is not a JSON object")
    digest = document.get("digest") or document.get("stream_sha256") or document.get("dump_sha256")
    session = document.get("session")
    if not isinstance(session, str):
        raise Failure(f"dataset report {path} has no session")
    objects = document.get("objects")
    active = objects.get("active_partitions") if isinstance(objects, dict) else None
    if not isinstance(digest, str):
        # A resumed import reuses an earlier database phase and carries no stream digest;
        # the object inventory (count|bytes of verified parts) still identifies the copy.
        digest = f"objects {active}" if isinstance(active, str) else "unavailable"
    counts = document.get("row_counts")
    counts = counts if isinstance(counts, dict) else {}
    return {
        "session": session,
        "digest": digest,
        "report": path.name,
        "profiles": counts.get("argo_profile"),
        "levels": counts.get("core_measurement"),
    }


def restart(command: str, client: Client) -> None:
    """Run the restart command once, then wait for the liveness route (which builds nothing)."""
    print("restarting the API for the cold pass", file=sys.stderr, flush=True)
    try:
        result = subprocess.run(command, shell=True, cwd=ROOT, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Failure(f"restart command failed to run: {error}") from None
    if result.returncode != 0:
        raise Failure(f"restart command exited with status {result.returncode}")
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if client.request("GET", "/v1/health/live", correlation="latency-ready").ok:
            return
        time.sleep(1.0)
    raise Failure(f"the API was not live {READY_TIMEOUT_S:.0f} s after the restart command")


def _warm(send: Callable[[], Call], cold: Call, warmup: int, runs: int) -> list[Call]:
    """Discarded warm-up calls, then recorded calls; a failed call is kept and ends the loop."""
    recorded: list[Call] = []
    if not cold.ok:
        return recorded
    for index in range(warmup + runs):
        call = send()
        if not call.ok:
            recorded.append(call)
            break
        if index >= warmup:
            recorded.append(call)
    return recorded


def run(args: argparse.Namespace, dataset: dict[str, Any] | None) -> dict[str, Any]:
    matrix = build_matrix()
    client = Client(args.base_url)
    if args.restart_command:
        restart(args.restart_command, client)
    entries = [*matrix["queries"], *matrix["metadata"]]

    def sender(entry: dict[str, Any]) -> Callable[[], Call]:
        if entry["kind"] == "metadata":
            return lambda: client.request(entry["method"], entry["path"])
        return lambda: client.query(entry["plan"])

    colds: list[Call] = []
    for entry in entries:
        call = sender(entry)()
        colds.append(call)
        print(
            f"cold {entry['label']}: {call.wall_ms:.1f} ms {'ok' if call.ok else call.error}",
            file=sys.stderr,
            flush=True,
        )
    rows = []
    parameters_body: dict[str, Any] | None = None
    for entry, cold in zip(entries, colds, strict=True):
        warm = _warm(sender(entry), cold, args.warmup, args.runs)
        row = summarise(entry, cold, warm)
        rows.append(row)
        if entry.get("path") == "/v1/catalog/parameters":
            parameters_body = next((c.body for c in [cold, *warm] if c.ok), None)
        print(
            f"warm {entry['label']}: p95 {_ms(row['warm_p95_ms'])} ms {row['status']}",
            file=sys.stderr,
            flush=True,
        )
    head, dirty = git_state()
    limits = _dig(parameters_body, "limits")
    meta = {
        "date": args.date,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_head": head,
        "git_dirty": dirty,
        "base_url": args.base_url,
        "runs": args.runs,
        "warmup": args.warmup,
        "restart_command": args.restart_command,
        "host": platform.platform(),
        "cpu_count": os.cpu_count(),
        "dataset": dataset,
        "limits": limits if isinstance(limits, dict) else None,
        "methodology": METHODOLOGY,
        "objectives": {
            "metadata_p95_ms": METADATA_OBJECTIVE_MS,
            "aggregate_p95_ms": AGGREGATE_OBJECTIVE_MS,
        },
    }
    queries = len(matrix["queries"])
    return build_report(meta, rows[:queries], rows[queries:])


def write_outputs(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"query_latency_{report['date']}.json"
    markdown_path = out_dir / f"query_latency_{report['date']}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_markdown(report))
    return json_path, markdown_path


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return value


def _iso_date(text: str) -> str:
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None


def _http_url(text: str) -> str:
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise argparse.ArgumentTypeError("expected an http(s) URL such as http://127.0.0.1:8000")
    return text.rstrip("/")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
        epilog="Exit status: 0 all requests succeeded on their expected route, 2 a request "
        "failed or ran on another route (files still written), 1 the run could not start.",
    )
    parser.add_argument("--base-url", type=_http_url, default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=_positive, default=20, help="warm repetitions per plan")
    parser.add_argument(
        "--warmup", type=_non_negative, default=2, help="discarded warm calls per plan"
    )
    parser.add_argument("--out", type=Path, default=Path("reports"), help="output directory")
    parser.add_argument(
        "--date",
        type=_iso_date,
        default=datetime.now(UTC).strftime("%Y-%m-%d"),
        help="report date, YYYY-MM-DD (default: today, UTC)",
    )
    parser.add_argument(
        "--dataset-report",
        type=Path,
        default=None,
        help="reports/stage2-dataset-*.json whose session and digest are copied into the report",
    )
    parser.add_argument(
        "--restart-command",
        default=None,
        help="shell command run once before the cold pass to empty the API process cache, "
        "for example 'make restart'",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset = load_dataset_report(args.dataset_report) if args.dataset_report else None
        report = run(args, dataset)
    except Failure as error:
        print(f"query latency run failed: {error}", file=sys.stderr)
        return 1
    json_path, markdown_path = write_outputs(report, args.out)
    print(f"wrote {json_path} and {markdown_path}")
    if report["failures"]:
        print(
            f"{report['failures']} row(s) failed or ran on an unexpected route; see the report",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
