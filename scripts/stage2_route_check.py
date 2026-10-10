"""Cross-route agreement check: the DuckDB plans of the latency matrix on both execution routes.

The ten DuckDB plans of ``scripts/query_latency.py`` (the whole-envelope aggregates) are run
twice against the dev dataset inside the running API container: once with the PostgreSQL route
forced (an unbounded PostgreSQL level budget) and once with the DuckDB route forced (a budget of
one level). Column names, row counts and every value must agree, numbers within a relative
tolerance that absorbs floating-point summation order. The outcome is written to
``reports/stage2-route-check_<date>.json`` and ``.md`` so the claim that both routes return the
same science is reproducible, not observed by hand (Stage 2 gate, known issues).

Host usage (the dev project must be running with the dataset imported):

    uv run --all-packages --frozen python scripts/stage2_route_check.py

The host side pipes this file into ``python - --inner`` in the API container, which holds the
query login, the part cache and the object-store credentials; nothing is printed but JSON.
"""

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-9


class Failure(RuntimeError):
    pass


# ----- comparison (pure; unit-tested offline) ------------------------------------------------


def compare_rows(
    left: list[list[Any]],
    right: list[list[Any]],
    *,
    rel_tol: float = RELATIVE_TOLERANCE,
    abs_tol: float = ABSOLUTE_TOLERANCE,
) -> dict[str, Any]:
    """Cell-by-cell comparison; returns the verdict with the largest relative difference seen."""
    if len(left) != len(right):
        return {"agree": False, "reason": f"row count {len(left)} != {len(right)}", "max_rel": None}
    worst = 0.0
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if len(a) != len(b):
            return {"agree": False, "reason": f"row {index} width differs", "max_rel": None}
        for column, (x, y) in enumerate(zip(a, b, strict=True)):
            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not (isinstance(x, int | float) and isinstance(y, int | float))
            ):
                if x != y:
                    return {
                        "agree": False,
                        "reason": f"row {index} column {column}: {x!r} != {y!r}",
                        "max_rel": None,
                    }
                continue
            if x is None or y is None:
                continue
            if not math.isclose(x, y, rel_tol=rel_tol, abs_tol=abs_tol):
                return {
                    "agree": False,
                    "reason": f"row {index} column {column}: {x!r} != {y!r}",
                    "max_rel": None,
                }
            scale = max(abs(x), abs(y))
            if scale > 0:
                worst = max(worst, abs(x - y) / scale)
    return {"agree": True, "reason": None, "max_rel": worst}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Stage 2 cross-route agreement check, {report['date']}",
        "",
        f"- Commit: `{report['git_head']}`",
        f"- Container: `{report['container']}`",
        f"- Tolerance: relative {report['rel_tol']:g}, absolute {report['abs_tol']:g}",
        f"- Dataset: {report.get('dataset') or 'the dev project database'}",
        "",
        "Each plan ran twice through `QueryService.query`: PostgreSQL route forced by an unbounded "
        "PostgreSQL level budget, DuckDB route forced by a budget of one level; the DuckDB plans "
        "are those of the latency matrix (`scripts/query_latency.py`).",
        "",
        "| plan | est. levels | rows | PostgreSQL ms | DuckDB ms | max relative difference "
        "| status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["plans"]:
        rel = row.get("max_rel")
        cells = [
            "-" if row.get(name) is None else str(row.get(name))
            for name in ("estimated_levels", "rows", "postgresql_ms", "duckdb_ms")
        ]
        lines.append(
            f"| {row['label']} | {' | '.join(cells)} | "
            f"{'-' if rel is None else format(rel, '.2e')} | {row['status']} |"
        )
    verdict = "PASS" if report["pass"] else "FAIL"
    lines += ["", f"Result: **{verdict}** ({report['agreeing']} of {report['total']} plans agree)."]
    failures = [row for row in report["plans"] if row["status"] != "ok"]
    for row in failures:
        lines.append(f"- {row['label']}: {row.get('reason') or row['status']}")
    return "\n".join(lines) + "\n"


def duckdb_plans() -> list[dict[str, Any]]:
    """The DuckDB group of the latency matrix (host side; the container gets them as JSON)."""
    sys.path.insert(0, str(ROOT))
    from scripts.query_latency import build_matrix

    return [entry for entry in build_matrix()["queries"] if entry["expected_route"] == "duckdb"]


# ----- inner mode: runs inside the API container --------------------------------------------


def run_inner(plans: list[dict[str, Any]], rel_tol: float, abs_tol: float) -> dict[str, Any]:
    from floatchat_api.query_api import object_fetcher
    from floatchat_core.config import Settings
    from floatchat_core.query.cache import PartCache
    from floatchat_core.query.catalogue import QueryCatalogue, engine_from_url
    from floatchat_core.query.errors import QueryError
    from floatchat_core.query.limits import QueryLimits
    from floatchat_core.query.router import QueryService

    settings = Settings()
    if settings.query_database_url is None or not settings.query_object_cache_dir:
        raise Failure("QUERY_DATABASE_URL and QUERY_OBJECT_CACHE_DIR are required")

    def service(**overrides: Any) -> QueryService:
        limits = QueryLimits(query_timeout_seconds=600, **overrides)
        engine = engine_from_url(settings.query_database_url.get_secret_value(), limits)
        cache = PartCache(
            Path(settings.query_object_cache_dir),
            limits.object_cache_bytes,
            object_fetcher(settings),
        )
        return QueryService(QueryCatalogue(engine, limits), limits, cache, "route-check")

    postgresql = service(postgres_level_budget=10**9)
    duckdb = service(postgres_level_budget=1, duckdb_level_budget=10**9)
    results = []
    for entry in plans:
        row: dict[str, Any] = {"label": entry["label"], "status": "ok"}
        sides: dict[str, Any] = {}
        for name, engine_service in (("postgresql", postgresql), ("duckdb", duckdb)):
            started = time.perf_counter()
            try:
                response = engine_service.query(entry["plan"])
            except QueryError as error:
                row["status"] = f"{name}: {error.code}"
                row["reason"] = error.text
                break
            row[f"{name}_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if response["execution"]["source"] != name:
                row["status"] = f"{name} route not taken"
                row["reason"] = f"router chose {response['execution']['source']}"
                break
            sides[name] = response
        if row["status"] != "ok":
            results.append(row)
            continue
        left, right = sides["postgresql"]["result"], sides["duckdb"]["result"]
        row["estimated_levels"] = sides["duckdb"]["execution"].get("estimated_levels")
        row["rows"] = left["row_count"]
        if [c["name"] for c in left["columns"]] != [c["name"] for c in right["columns"]]:
            row["status"] = "mismatch"
            row["reason"] = "column names differ"
        else:
            verdict = compare_rows(left["rows"], right["rows"], rel_tol=rel_tol, abs_tol=abs_tol)
            row["max_rel"] = verdict["max_rel"]
            if not verdict["agree"]:
                row["status"] = "mismatch"
                row["reason"] = verdict["reason"]
        results.append(row)
    agreeing = sum(1 for row in results if row["status"] == "ok")
    return {
        "plans": results,
        "total": len(results),
        "agreeing": agreeing,
        "pass": agreeing == len(results) and bool(results),
    }


# ----- host mode ----------------------------------------------------------------------------


def api_container() -> str:
    sys.path.insert(0, str(ROOT))
    from scripts.dev import configuration_root

    project = "floatchat-dev"
    for line in (configuration_root() / ".env").read_text().splitlines():
        if line.startswith("COMPOSE_PROJECT_NAME="):
            project = line.split("=", 1)[1].strip().strip("\"'")
    return f"{project}-api-1"


def run_host(args: argparse.Namespace) -> int:
    container = args.container or api_container()
    plans = duckdb_plans()
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "python",
        "-",
        "--inner",
        "--plans",
        json.dumps(plans),
        "--rel-tol",
        str(args.rel_tol),
        "--abs-tol",
        str(args.abs_tol),
    ]
    result = subprocess.run(
        command, input=Path(__file__).read_bytes(), capture_output=True, timeout=7200
    )
    if result.returncode != 0:
        raise Failure("inner run failed: " + result.stderr.decode(errors="replace")[-1500:])
    inner = json.loads(result.stdout.decode().strip().splitlines()[-1])
    head = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    dataset = None
    if args.dataset_report and args.dataset_report.exists():
        document = json.loads(args.dataset_report.read_text())
        dataset = f"session {document.get('session')} ({args.dataset_report.name})"
    report = {
        "kind": "stage2_route_check",
        "date": args.date,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_head": head or "unknown",
        "container": container,
        "rel_tol": args.rel_tol,
        "abs_tol": args.abs_tol,
        "dataset": dataset,
        **inner,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"stage2-route-check_{args.date}.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    (args.out / f"stage2-route-check_{args.date}.md").write_text(render_markdown(report))
    print(
        f"{'PASS' if report['pass'] else 'FAIL'}: {report['agreeing']} of {report['total']} plans "
        f"agree; wrote {args.out / f'stage2-route-check_{args.date}.md'}"
    )
    return 0 if report["pass"] else 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plans", help=argparse.SUPPRESS)
    parser.add_argument("--container", default=None)
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    parser.add_argument(
        "--dataset-report", type=Path, default=ROOT / "reports/stage2-dataset-302412131a7c99fb.json"
    )
    parser.add_argument("--rel-tol", type=float, default=RELATIVE_TOLERANCE)
    parser.add_argument("--abs-tol", type=float, default=ABSOLUTE_TOLERANCE)
    args = parser.parse_args()
    try:
        if args.inner:
            print(json.dumps(run_inner(json.loads(args.plans or "[]"), args.rel_tol, args.abs_tol)))
            return
        raise SystemExit(run_host(args))
    except Failure as error:
        print(f"route check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
