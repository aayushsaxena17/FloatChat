"""Chart contract (PRD section 11.3; plan section 5.3): semantic spec plus allow-listed Plotly."""

from typing import Any

from .errors import QueryError
from .limits import QueryLimits
from .plan import QueryPlan
from .sanitize import ColumnSpec, SanitizedResult

TRACE_TYPES = frozenset({"scatter", "scattergl", "histogram", "scattergeo"})
TRACE_KEYS = frozenset({"type", "mode", "name", "x", "y", "lon", "lat", "text", "nbinsx"})
LABELS = {
    "temperature": "Temperature",
    "salinity": "Practical salinity",
    "pressure": "Pressure",
    "month": "Month",
    "day": "Day",
    "profile": "Profile",
    "float": "Float",
    "depth_bin": "Depth bin",
    "region": "Region",
    "distance_m": "Distance",
    "observed_at": "Observed at",
    "longitude": "Longitude",
    "latitude": "Latitude",
    "level_index": "Level",
}


def _label(column: str) -> str:
    for prefix, label in LABELS.items():
        if column == prefix:
            return label
        if column.startswith(prefix + "_"):
            return f"{label} {column[len(prefix) + 1 :]}"
    return column


def _axis(column: ColumnSpec, *, reversed_axis: bool = False) -> dict[str, Any]:
    return {
        "field": column.name,
        "label": _label(column.name),
        "unit": column.unit,
        "reversed": reversed_axis,
    }


def _bounded(points: int, series: int, limits: QueryLimits) -> None:
    if points > limits.chart_points_per_series or series > limits.chart_series:
        raise QueryError(
            "result_too_large", message="The chart exceeds the configured cardinality limits."
        )


def _spec(
    kind: str,
    x: ColumnSpec,
    y: ColumnSpec | None,
    series: list[str],
    traces: list[dict[str, Any]],
    aggregation: str,
    *,
    reversed_y: bool = False,
) -> dict[str, Any]:
    for trace in traces:
        if trace["type"] not in TRACE_TYPES or not set(trace) <= TRACE_KEYS:
            raise QueryError("internal_error", message="Chart trace outside the allow-list.")
    return {
        "type": kind,
        "encodings": {
            "x": _axis(x),
            "y": None if y is None else _axis(y, reversed_axis=reversed_y),
            "series": {"field": "name", "label": "Series", "unit": None, "reversed": False},
        },
        "axis": {"x": _axis(x), "y": None if y is None else _axis(y, reversed_axis=reversed_y)},
        "series": series,
        "missing_value_policy": "null",
        "aggregation": aggregation,
        "data": {
            "inline": True,
            "points": sum(len(trace.get("x", [])) + len(trace.get("lon", [])) for trace in traces),
            "url": None,
        },
        "provenance_ref": "provenance",
        "plotly": {
            "traces": traces,
            "layout": {
                "xaxis": {"title": _label(x.name) + (f" ({x.unit})" if x.unit else "")},
                "yaxis": {
                    "title": (_label(y.name) + (f" ({y.unit})" if y.unit else "")) if y else "",
                    "autorange": "reversed" if reversed_y else True,
                },
            },
        },
    }


def _column_values(result: SanitizedResult, name: str) -> list[Any]:
    index = [column.name for column in result.columns].index(name)
    return [row[index] for row in result.rows]


def compile_chart(
    plan: QueryPlan, result: SanitizedResult, limits: QueryLimits, aggregation: str
) -> dict[str, Any] | None:
    kind = plan.presentation.kind
    if kind == "table":
        return None
    names = [column.name for column in result.columns]
    by_name = {column.name: column for column in result.columns}
    traces: list[dict[str, Any]] = []
    if kind in ("line_chart", "scatter"):
        keys = [name for name in names if name in LABELS and by_name[name].unit is None]
        key = keys[0] if keys else None
        if key is None:
            raise QueryError("internal_error", message="Chart needs a group key.")
        metrics = [name for name in names if name not in keys]
        series_key = keys[1] if len(keys) > 1 else None
        series_values = sorted(set(_column_values(result, series_key))) if series_key else [None]
        traces = []
        xs = _column_values(result, key)
        series_names = []
        for metric in metrics:
            ys = _column_values(result, metric)
            for series_value in series_values:
                selector = (
                    [True] * len(xs)
                    if series_key is None
                    else [value == series_value for value in _column_values(result, series_key)]
                )
                name = metric if series_value is None else f"{metric} {series_value}"
                series_names.append(name)
                traces.append(
                    {
                        "type": "scatter",
                        "mode": "lines+markers" if kind == "line_chart" else "markers",
                        "name": name,
                        "x": [x for x, keep in zip(xs, selector, strict=True) if keep],
                        "y": [y for y, keep in zip(ys, selector, strict=True) if keep],
                    }
                )
        _bounded(max((len(t["x"]) for t in traces), default=0), len(traces), limits)
        y_spec = by_name[metrics[0]] if metrics else None
        return _spec(kind, by_name[key], y_spec, series_names, traces, aggregation)
    if kind == "histogram":
        metrics = [name for name in names if by_name[name].type == "number"]
        if not metrics:
            raise QueryError("internal_error", message="Histogram needs a numeric column.")
        traces = []
        for metric in metrics:
            values = [v for v in _column_values(result, metric) if v is not None]
            traces.append(
                {
                    "type": "histogram",
                    "name": metric,
                    "x": values,
                    "nbinsx": plan.presentation.bins or 50,
                }
            )
        _bounded(max(len(t["x"]) for t in traces), len(traces), limits)
        return _spec(
            kind, by_name[metrics[0]], ColumnSpec("count", "integer"), metrics, traces, aggregation
        )
    if kind == "map":
        lons, lats = _column_values(result, "longitude"), _column_values(result, "latitude")
        labels = (
            _column_values(result, "platform_number")
            if "platform_number" in names
            else [""] * len(lons)
        )
        _bounded(len(lons), 1, limits)
        trace = {
            "type": "scattergeo",
            "mode": "markers",
            "name": "profiles",
            "lon": lons,
            "lat": lats,
            "text": labels,
        }
        return _spec(
            kind, by_name["longitude"], by_name["latitude"], ["profiles"], [trace], aggregation
        )
    if kind in ("profile_plot", "ts_diagram"):
        profiles = sorted(set(_column_values(result, "profile_id")))
        pressures = _column_values(result, "pressure")
        ids = _column_values(result, "profile_id")
        traces = []
        if kind == "profile_plot":
            variable = next(v for v in plan.ordered_variables if v != "pressure")
            values = _column_values(result, variable)
            for identifier in profiles:
                traces.append(
                    {
                        "type": "scatter",
                        "mode": "lines+markers",
                        "name": identifier,
                        "x": [v for v, i in zip(values, ids, strict=True) if i == identifier],
                        "y": [p for p, i in zip(pressures, ids, strict=True) if i == identifier],
                    }
                )
            x_spec, y_spec, reversed_y = by_name[variable], by_name["pressure"], True
        else:
            temperatures = _column_values(result, "temperature")
            salinities = _column_values(result, "salinity")
            for identifier in profiles:
                traces.append(
                    {
                        "type": "scatter",
                        "mode": "markers",
                        "name": identifier,
                        "x": [s for s, i in zip(salinities, ids, strict=True) if i == identifier],
                        "y": [t for t, i in zip(temperatures, ids, strict=True) if i == identifier],
                    }
                )
            x_spec, y_spec, reversed_y = by_name["salinity"], by_name["temperature"], False
        _bounded(max((len(t["x"]) for t in traces), default=0), len(traces), limits)
        return _spec(kind, x_spec, y_spec, profiles, traces, aggregation, reversed_y=reversed_y)
    raise QueryError("internal_error", message="Unsupported presentation.")
