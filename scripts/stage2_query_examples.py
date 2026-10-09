"""Regenerate docs/stage2-query-engine.md statement blocks from the current compilers."""

import re
from pathlib import Path

from floatchat_core.query import compile_duckdb, compile_sql
from floatchat_core.query.geography import resolve_geography
from floatchat_core.query.plan import validate_plan

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/stage2-query-engine.md"
EXAMPLE = {
    "dataset": "core",
    "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "depth_dbar": {"min": 0, "max": 100},
    "variables": ["temperature", "salinity"],
    "qc_policy": "science_ready",
    "operation": {
        "kind": "aggregate",
        "group_by": ["month"],
        "metrics": ["mean", "count"],
        "unit": "profile",
    },
    "presentation": {"kind": "line_chart"},
}
NEAREST = {
    "time_range": {"start": "2025-03-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
    "geography": {"kind": "point_radius", "longitude": 70, "latitude": 10, "radius_km": 500},
    "variables": ["temperature"],
    "operation": {"kind": "nearest", "longitude": 70, "latitude": 10, "radius_km": 500, "k": 10},
}


def blocks() -> list[str]:
    plan = validate_plan(EXAMPLE)
    geography = resolve_geography(plan.geography)
    nearest = validate_plan(NEAREST)
    duck = compile_duckdb.aggregate_statement(plan, label=geography.label, max_rows=50000)
    return [
        compile_sql.render(compile_sql.aggregate_statement(plan, geography, max_rows=50000)),
        compile_sql.render(
            compile_sql.nearest_statement(nearest, resolve_geography(nearest.geography))
        ),
        duck.sql,
    ]


def main() -> None:
    text = DOC.read_text()
    pattern = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)
    rendered = blocks()
    found = pattern.findall(text)
    if len(found) != len(rendered):
        raise SystemExit(f"expected {len(rendered)} sql blocks, found {len(found)}")
    cursor = iter(rendered)
    DOC.write_text(pattern.sub(lambda _match: "```sql\n" + next(cursor) + "\n```", text))
    print("docs/stage2-query-engine.md statements regenerated")


if __name__ == "__main__":
    main()
