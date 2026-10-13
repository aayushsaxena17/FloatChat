"""Bounded result summary, deterministic template narrative and numeric grounding (ADR-0073).

The model never sees a whole result: ``summarize`` keeps the columns with units, counts, the
first rows and per-column extrema. ``template`` always exists; a model narrative replaces it only
when every number it states appears in the summary (``grounded``).
"""

import re
from typing import Any

SUMMARY_ROWS = 12
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def summarize(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") or {}
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    stats: dict[str, dict[str, float]] = {}
    for index, column in enumerate(columns):
        values = [row[index] for row in rows if index < len(row) and _finite(row[index])]
        if values and column.get("type") in ("number", "integer"):
            stats[column["name"]] = {
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "mean": round(sum(values) / len(values), 3),
                "count": len(values),
            }
    coverage = response.get("coverage") or {}
    execution = response.get("execution") or {}
    interpretation = response.get("interpretation") or {}
    # Rounded rows: the model copies what it is shown, and a narrative should read
    # "25.823 degree_C", not a 15-digit float (first live run, 2026-10-13).
    shown = [
        [round(cell, 3) if isinstance(cell, float) else cell for cell in row]
        for row in rows[:SUMMARY_ROWS]
    ]
    return {
        "columns": [{"name": column.get("name"), "unit": column.get("unit")} for column in columns],
        "row_count": int(result.get("row_count") or len(rows)),
        "rows": shown,
        "rows_shown": min(len(rows), SUMMARY_ROWS),
        "stats": stats,
        "partial": bool(response.get("partial")),
        "coverage": {
            "slots_total": coverage.get("slots_total"),
            "slots_covered": coverage.get("slots_covered"),
            "slots_missing": coverage.get("slots_missing"),
            "estimated_profiles": coverage.get("estimated_profiles"),
        },
        "source": execution.get("source"),
        "transformation": interpretation.get("transformation"),
        "time_range": interpretation.get("time_range"),
        "geography": interpretation.get("geography"),
        "depth_dbar": interpretation.get("depth_dbar"),
        "variables": interpretation.get("variables"),
        "qc_policy": (interpretation.get("qc_policy") or {}).get("name"),
        "operation": interpretation.get("operation"),
        "presentation": interpretation.get("presentation"),
    }


def _geography_text(geography: dict[str, Any] | None) -> str:
    if not geography:
        return "the requested area"
    kind = geography.get("kind")
    if kind == "named_region":
        return f"the {geography.get('name')}"
    if kind == "bbox":
        boxes = geography.get("boxes") or []
        if boxes:
            box = boxes[0]
            return (
                f"the box {box['west']:.1f} to {box['east']:.1f} E, "
                f"{box['south']:.1f} to {box['north']:.1f} N"
            )
        return "the bounding box"
    if kind == "point_radius":
        return (
            f"within {geography.get('radius_m', 0) / 1000:.0f} km of "
            f"{geography.get('latitude')} N, {geography.get('longitude')} E"
        )
    return "the requested area"


UNIT_TEXT = {"degree_C": "°C", "dbar": "dbar", "1": "", "degrees_east": "°E", "degrees_north": "°N"}
METRIC_TEXT = {
    "mean": "mean",
    "count": "count",
    "min": "minimum",
    "max": "maximum",
    "stddev": "standard deviation",
    "median": "median",
}
POLICY_TEXT = {
    "science_ready": "science-ready QC",
    "mode_selected": "all delivered values regardless of QC",
    "raw": "raw stored columns",
}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _label(column: str) -> str:
    """``temperature_mean`` -> ``mean temperature``; other names keep their words."""
    parts = column.split("_")
    if len(parts) >= 2 and parts[-1] in METRIC_TEXT:
        return f"{METRIC_TEXT[parts[-1]]} {' '.join(parts[:-1])}"
    return column.replace("_", " ")


def _period_text(period: dict[str, Any]) -> str:
    """Whole months read as month names; anything else as dates (end exclusive)."""
    start, end = str(period.get("start", ""))[:10], str(period.get("end", ""))[:10]
    try:
        sy, sm, sd = (int(part) for part in start.split("-"))
        ey, em, ed = (int(part) for part in end.split("-"))
    except ValueError:
        return f"{start} to {end}"
    if sd == 1 and ed == 1:
        last_month, last_year = (em - 1, ey) if em > 1 else (12, ey - 1)
        first = f"{MONTHS[sm - 1]} {sy}"
        last = f"{MONTHS[last_month - 1]} {last_year}"
        return first if first == last else f"{first} to {last}"
    return f"{start} to {end} (end exclusive)"


def template(summary: dict[str, Any]) -> str:
    """The deterministic narrative: what was computed and the extrema, in plain words."""
    operation = summary.get("operation") or {}
    kind = operation.get("kind", "query")
    variables = " and ".join(summary.get("variables") or [])
    when = _period_text(summary.get("time_range") or {})
    where = _geography_text(summary.get("geography"))
    depth = summary.get("depth_dbar")
    depth_text = f", {depth['min']:.0f} to {depth['max']:.0f} dbar" if depth else ""
    policy = POLICY_TEXT.get(summary.get("qc_policy") or "science_ready", "science-ready QC")
    rows = summary.get("row_count", 0)
    if kind == "aggregate":
        metrics = " and ".join(METRIC_TEXT.get(m, m) for m in operation.get("metrics") or [])
        keys = operation.get("group_by") or []
        grouping = f" by {' and '.join(key.replace('_', ' ') for key in keys)}" if keys else ""
        unit = operation.get("unit", "profile")
        first = (
            f"{metrics.capitalize()} {variables}{grouping} in {where}, {when}{depth_text}, "
            f"one value per {unit} with {policy}: {rows} rows."
        )
    elif kind == "nearest":
        first = (
            f"The {operation.get('k')} nearest profiles to the point, {when}, with {policy}: "
            f"{rows} rows."
        )
    else:
        first = f"Profiles in {where}, {when}{depth_text}, with {policy}: {rows} rows."
    first = first.replace(": 1 rows.", ": 1 row.")
    sentences = [first]
    stats = summary.get("stats") or {}
    units = {column["name"]: column.get("unit") for column in summary.get("columns") or []}
    counts = [
        (name[: -len("_count")].replace("_", " "), values["min"])
        for name, values in stats.items()
        if name.endswith("_count") and values["count"] == 1
    ]
    if counts and rows == 1:
        what = "profiles" if operation.get("unit", "profile") == "profile" else "measurements"
        sentences.append(
            "; ".join(f"{int(value)} {what} have {label} values" for label, value in counts) + "."
        )
    for name, values in list(stats.items())[:4]:
        if name.endswith("_count") or name in ("level_count", "cycle_number", "level_index"):
            continue
        unit = UNIT_TEXT.get(units.get(name) or "", units.get(name) or "")
        unit_text = f" {unit}".rstrip() if unit else ""
        label = _label(name).capitalize()
        if values["count"] > 1:
            sentences.append(
                f"{label} ranges from {values['min']}{unit_text} to {values['max']}{unit_text}."
            )
        else:
            sentences.append(f"{label} is {values['min']}{unit_text}.")
    coverage = summary.get("coverage") or {}
    if summary.get("partial"):
        sentences.append(
            f"The result is partial: {coverage.get('slots_missing')} of "
            f"{coverage.get('slots_total')} coverage slots are missing."
        )
    if rows == 0:
        sentences.append("No values matched; try a wider period, area or depth band.")
    return " ".join(sentences)


def _numbers(text: str) -> set[str]:
    found = set()
    for match in NUMBER.findall(text):
        value = float(match)
        found.add(f"{value:.2f}")
        found.add(f"{abs(value):.2f}")
    return found


def allowed_numbers(summary: dict[str, Any]) -> set[str]:
    """Every number the narrative may state: the summary's values, rounded forms, and the
    digits of the plan's dates, depths and coordinates."""
    allowed: set[str] = set()
    for row in summary.get("rows") or []:
        for cell in row:
            if _finite(cell):
                allowed |= _numbers(str(cell))
                allowed |= _numbers(f"{cell:.1f}")
                allowed |= _numbers(f"{cell:.0f}")
            elif isinstance(cell, str):
                allowed |= _numbers(cell)
    for values in (summary.get("stats") or {}).values():
        for value in values.values():
            allowed |= _numbers(str(value))
            allowed |= _numbers(f"{value:.1f}")
            allowed |= _numbers(f"{value:.0f}")
    for key in ("row_count", "rows_shown"):
        allowed |= _numbers(str(summary.get(key, "")))
    for value in (summary.get("coverage") or {}).values():
        if value is not None:
            allowed |= _numbers(str(value))
    for key in ("time_range", "geography", "depth_dbar", "operation", "transformation"):
        allowed |= _numbers(str(summary.get(key, "")))
    return allowed


def grounded(narrative: str, summary: dict[str, Any]) -> bool:
    """True when every number in the narrative appears in the summary (ADR-0073)."""
    allowed = allowed_numbers(summary)
    for match in NUMBER.findall(narrative):
        value = float(match)
        if f"{value:.2f}" not in allowed and f"{abs(value):.2f}" not in allowed:
            # Small ordinals ("two sentences", "3 rows") are allowed when they are counts.
            if value.is_integer() and 0 <= value <= 4:
                continue
            return False
    return True
