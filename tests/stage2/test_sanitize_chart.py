"""Result sanitiser (PRD 8.5) and chart compiler (plan section 5.3) without a database."""

import json
import math
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from floatchat_core.query import chart
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import validate_plan
from floatchat_core.query.sanitize import ColumnSpec, check_text, sanitize, unit_for

LIMITS = QueryLimits()
S, N, INT = "string", "number", "integer"
ONE = (ColumnSpec("v", N),)
BASE = {
    "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "variables": ["temperature", "salinity"],
    "operation": {"kind": "profiles", "limit": 10},
}


def sanitized(columns, rows, limits=LIMITS):
    return sanitize(
        [dict(zip([c.name for c in columns], row, strict=True)) for row in rows], columns, limits
    )


def error_code(columns, rows, limits=LIMITS):
    with pytest.raises(QueryError) as caught:
        sanitized(columns, rows, limits)
    return caught.value


def test_non_finite_numbers_become_null_and_are_counted():
    rows = [(math.nan,), (math.inf,), (-math.inf,), (1.5,), (Decimal("NaN"),), (None,)]
    result = sanitized(ONE, rows)
    assert result.rows == [[None], [None], [None], [1.5], [None], [None]]
    assert result.non_finite == 4
    assert result.as_dict()["non_finite_values"] == 4 and result.as_dict()["row_count"] == 6


def test_scalar_conversions():
    columns = (
        ColumnSpec("d", N), ColumnSpec("n", INT), ColumnSpec("at", "timestamp"),
        ColumnSpec("day", "date"), ColumnSpec("id", S), ColumnSpec("ok", "boolean"),
        ColumnSpec("f", N, "degree_C"),
    )  # fmt: skip
    identifier = uuid.UUID("00000000-0000-4000-8000-000000000101")
    moment = datetime(2025, 3, 5, 12, 30, tzinfo=UTC)
    result = sanitized(
        columns, [(Decimal("1.25"), 7, moment, date(2025, 3, 5), identifier, True, 3)]
    )
    assert result.rows == [
        [1.25, 7, "2025-03-05T12:30:00Z", "2025-03-05", str(identifier), True, 3]
    ]
    assert isinstance(result.rows[0][0], float) and result.non_finite == 0
    assert result.bytes == len(json.dumps(result.rows, separators=(",", ":")).encode())
    assert result.columns[6].as_dict() == {"name": "f", "type": N, "unit": "degree_C"}
    assert result.as_dict()["missing_value_policy"] == "null"


def test_non_utc_timestamps_are_rendered_in_utc():
    local = datetime(2025, 3, 5, 18, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert sanitized((ColumnSpec("at", "timestamp"),), [(local,)]).rows == [
        ["2025-03-05T12:30:00Z"]
    ]


@pytest.mark.parametrize(
    "text",
    [
        "normalised/sha256/" + "a" * 64 + ".parquet",
        "raw/sha256/abc",
        "postgresql://floatchat:pw@db/floatchat",
        "postgres://u@h/d",
        "s3://bucket/key",
        "http://minio:9000/bucket",
        "Traceback (most recent call last)",
        "SELECT 1",
        "insert into x",
        "my Password",
        "client SECRET",
        "x" * 513,
    ],
)
def test_forbidden_or_overlong_strings_are_an_internal_error(text):
    error = error_code((ColumnSpec("v", S),), [(text,)])
    assert error.code == "internal_error" and error.status == 500
    assert text not in json.dumps(error.as_dict("c"))
    with pytest.raises(QueryError):
        check_text(text)


def test_ordinary_strings_pass():
    for text in ("Arabian Sea", "selected", "5900001", "x" * 512, "naïve ocean"):
        assert sanitized((ColumnSpec("v", S),), [(text,)]).rows == [[text]]
        assert check_text(text) == text


@pytest.mark.parametrize(
    ("spec", "value"),
    [
        (S, 1), (S, 1.5), (S, True), (N, "1"), (N, True), (INT, 1.5), (INT, "1"), (INT, True),
        ("boolean", 1), ("boolean", "yes"), ("timestamp", "2025-01-01"), ("date", datetime(2025, 1, 1, tzinfo=UTC)),
        (N, b"bytes"), (N, [1]), (S, {"a": 1}), (S, object()),
    ],
)  # fmt: skip
def test_type_mismatch_is_an_internal_error(spec, value):
    assert error_code((ColumnSpec("v", spec),), [(value,)]).code == "internal_error"


def test_row_shape_mismatch_is_an_internal_error():
    columns = (ColumnSpec("a", N), ColumnSpec("b", N))
    for row in ({"a": 1}, {"a": 1, "b": 2, "c": 3}, {"a": 1, "x": 2}):
        with pytest.raises(QueryError) as caught:
            sanitize([row], columns, LIMITS)
        assert caught.value.code == "internal_error"


def test_row_and_byte_limits():
    small = QueryLimits(max_rows=3)
    assert len(sanitized(ONE, [(1.0,)] * 3, small).rows) == 3
    assert error_code(ONE, [(1.0,)] * 4, small).code == "result_too_large"
    assert error_code(ONE, [(1.0,)] * 4, small).status == 422
    tight = QueryLimits(response_bytes=65536)
    text = (ColumnSpec("v", S),)
    assert sanitized(text, [("y" * 100,)] * 500, tight).bytes < 65536
    assert error_code(text, [("y" * 100,)] * 1000, tight).code == "result_too_large"


@pytest.mark.parametrize(
    ("column", "unit"),
    [
        ("pressure", "dbar"), ("pressure_adjusted", "dbar"), ("temperature", "degree_C"),
        ("temperature_mean", "degree_C"), ("temperature_stddev", "degree_C"), ("salinity", "1"),
        ("salinity_median", "1"), ("distance_m", "m"), ("temperature_count", None),
        ("salinity_count", None), ("temperature_qc", None), ("temperature_adjusted_qc", None),
        ("pressure_data_mode", None), ("temperature_unit", None), ("month", None),
        ("platform_number", None), ("depth_bin", None), ("longitude", None),
    ],
)  # fmt: skip
def test_unit_for(column, unit):
    assert unit_for(column) == unit


# ----- chart compiler ----------------------------------------------------------------------------
def plan_for(operation, presentation, **changes):
    return validate_plan(BASE | {"operation": operation, "presentation": presentation} | changes)


def aggregate(keys=("month",), **extra):
    return {"kind": "aggregate", "group_by": list(keys), "metrics": ["mean"]} | extra


def table(**types):
    return tuple(ColumnSpec(name, kind, unit_for(name)) for name, kind in types.items())


def assert_allow_listed(spec):
    traces = spec["plotly"]["traces"]
    assert traces
    for trace in traces:
        assert trace["type"] in chart.TRACE_TYPES and set(trace) <= chart.TRACE_KEYS
    json.dumps(spec)


def test_table_has_no_chart():
    result = sanitized(table(month=S), [("2025-01",)])
    assert (
        chart.compile_chart(plan_for(aggregate(), {"kind": "table"}), result, LIMITS, "text")
        is None
    )


def test_line_chart_with_a_month_key_and_a_series_key():
    plan = plan_for(
        aggregate(("month", "float")), {"kind": "line_chart"}, variables=["temperature"]
    )
    columns = table(month=S, float=S, temperature_mean=N)
    rows = [("2025-01", "590", 10.0), ("2025-02", "590", None), ("2025-01", "591", 12.0)]
    spec = chart.compile_chart(plan, sanitized(columns, rows), LIMITS, "mean of profile means")
    assert spec["type"] == "line_chart" and spec["aggregation"] == "mean of profile means"
    assert spec["encodings"]["x"] == {
        "field": "month",
        "label": "Month",
        "unit": None,
        "reversed": False,
    }
    assert spec["encodings"]["y"]["field"] == "temperature_mean"
    assert (
        spec["encodings"]["y"]["unit"] == "degree_C"
        and spec["encodings"]["y"]["label"] == "Temperature mean"
    )
    assert spec["axis"]["y"]["reversed"] is False and spec["axis"]["x"]["field"] == "month"
    assert spec["series"] == ["temperature_mean 590", "temperature_mean 591"]
    assert spec["missing_value_policy"] == "null" and spec["provenance_ref"] == "provenance"
    first, second = spec["plotly"]["traces"]
    assert (first["x"], first["y"]) == (["2025-01", "2025-02"], [10.0, None])  # nulls stay null
    assert (second["x"], second["y"]) == (["2025-01"], [12.0])
    assert first["mode"] == "lines+markers" and first["name"] == "temperature_mean 590"
    assert spec["plotly"]["layout"]["yaxis"]["autorange"] is True
    assert_allow_listed(spec)
    assert {"type", "encodings", "axis", "series", "data", "plotly"} <= set(spec)


def test_line_chart_cardinality_limits():
    plan = plan_for(
        aggregate(("month", "float")), {"kind": "line_chart"}, variables=["temperature"]
    )
    columns = table(month=S, float=S, temperature_mean=N)
    rows = [("2025-01", "590", 1.0), ("2025-02", "590", 2.0), ("2025-01", "591", 3.0)]
    for limits in (QueryLimits(chart_points_per_series=1), QueryLimits(chart_series=1)):
        with pytest.raises(QueryError) as caught:
            chart.compile_chart(plan, sanitized(columns, rows), limits, "")
        assert caught.value.code == "result_too_large"
    ok = QueryLimits(chart_points_per_series=2, chart_series=2)
    assert chart.compile_chart(plan, sanitized(columns, rows), ok, "")


def test_scatter_uses_markers_on_the_first_key():
    plan = plan_for(
        aggregate(("depth_bin",), depth_bin_size=50), {"kind": "scatter"}, variables=["salinity"]
    )
    result = sanitized(table(depth_bin=N, salinity_mean=N), [(0.0, 34.5), (50.0, 34.9)])
    spec = chart.compile_chart(plan, result, LIMITS, "")
    assert spec["type"] == "scatter" and spec["plotly"]["traces"][0]["mode"] == "markers"
    assert spec["encodings"]["x"]["label"] == "Depth bin" and spec["series"] == ["salinity_mean"]
    assert_allow_listed(spec)


def test_histogram_bins_and_nulls():
    result = sanitized(
        table(month=S, temperature_mean=N, salinity_mean=N),
        [("a", 1.0, None), ("b", None, 2.0), ("c", 3.0, 4.0)],
    )
    for bins, expected in ((20, 20), (None, 50)):
        presentation = {"kind": "histogram"} | ({} if bins is None else {"bins": bins})
        spec = chart.compile_chart(plan_for(aggregate(), presentation), result, LIMITS, "")
        temperature, salinity = spec["plotly"]["traces"]
        assert temperature["type"] == "histogram" and temperature["nbinsx"] == expected
        assert temperature["x"] == [1.0, 3.0] and salinity["x"] == [2.0, 4.0]
        assert spec["encodings"]["y"]["field"] == "count" and spec["series"] == [
            "temperature_mean",
            "salinity_mean",
        ]
        assert_allow_listed(spec)
    with pytest.raises(QueryError) as caught:
        chart.compile_chart(
            plan_for(aggregate(), {"kind": "histogram"}),
            sanitized(table(month=S), [("a",)]),
            LIMITS,
            "",
        )
    assert caught.value.code == "internal_error"


@pytest.mark.parametrize("with_names", [True, False])
def test_map_emits_bounded_points(with_names):
    nearest = {"kind": "nearest", "longitude": 65.0, "latitude": 15.0, "radius_km": 100, "k": 5}
    plan = plan_for(nearest, {"kind": "map"})
    columns = table(longitude=N, latitude=N, **({"platform_number": S} if with_names else {}))
    rows = [(65.0, 15.0, "590"), (66.0, 16.0, "591")]
    result = sanitized(columns, [row[: len(columns)] for row in rows])
    spec = chart.compile_chart(plan, result, LIMITS, "")
    (trace,) = spec["plotly"]["traces"]
    assert trace["type"] == "scattergeo" and (trace["lon"], trace["lat"]) == (
        [65.0, 66.0],
        [15.0, 16.0],
    )
    assert trace["text"] == (["590", "591"] if with_names else ["", ""])
    assert (
        spec["encodings"]["x"]["field"] == "longitude"
        and spec["encodings"]["y"]["field"] == "latitude"
    )
    assert_allow_listed(spec)
    with pytest.raises(QueryError) as caught:
        chart.compile_chart(plan, result, QueryLimits(chart_points_per_series=1), "")
    assert caught.value.code == "result_too_large"


def profile_rows():
    return [("p1", 5.0, 20.0, 35.0), ("p1", 50.0, 18.0, 35.2), ("p2", 5.0, 21.0, 34.8)]


def test_profile_plot_reverses_the_pressure_axis():
    plan = plan_for(
        {"kind": "profiles", "limit": 10},
        {"kind": "profile_plot"},
        variables=["temperature", "pressure"],
    )
    columns = table(profile_id=S, pressure=N, temperature=N, salinity=N)
    spec = chart.compile_chart(plan, sanitized(columns, profile_rows()), LIMITS, "")
    assert spec["type"] == "profile_plot" and spec["series"] == ["p1", "p2"]
    assert (
        spec["encodings"]["x"]["field"] == "temperature"
        and spec["encodings"]["y"]["field"] == "pressure"
    )
    assert spec["encodings"]["y"]["reversed"] is True and spec["axis"]["y"]["reversed"] is True
    assert (
        spec["axis"]["y"]["unit"] == "dbar"
        and spec["plotly"]["layout"]["yaxis"]["autorange"] == "reversed"
    )
    first, second = spec["plotly"]["traces"]
    assert (first["x"], first["y"]) == ([20.0, 18.0], [5.0, 50.0]) and second["y"] == [5.0]
    assert_allow_listed(spec)


def test_ts_diagram_plots_salinity_against_temperature_per_profile():
    plan = plan_for({"kind": "profiles", "limit": 10}, {"kind": "ts_diagram"})
    columns = table(profile_id=S, pressure=N, temperature=N, salinity=N)
    spec = chart.compile_chart(plan, sanitized(columns, profile_rows()), LIMITS, "")
    assert spec["type"] == "ts_diagram" and spec["series"] == ["p1", "p2"]
    assert (
        spec["encodings"]["x"]["field"] == "salinity"
        and spec["encodings"]["y"]["field"] == "temperature"
    )
    assert spec["encodings"]["y"]["reversed"] is False and spec["axis"]["y"]["reversed"] is False
    first, _ = spec["plotly"]["traces"]
    assert (first["x"], first["y"]) == ([35.0, 35.2], [20.0, 18.0]) and first["mode"] == "markers"
    assert_allow_listed(spec)
    with pytest.raises(QueryError):
        chart.compile_chart(
            plan, sanitized(columns, profile_rows()), QueryLimits(chart_series=1), ""
        )


def test_line_chart_without_a_group_key_column_is_an_internal_error():
    plan = plan_for(aggregate(("day",)), {"kind": "line_chart"})
    result = sanitized(table(temperature_mean=N), [(1.0,)])
    with pytest.raises(QueryError) as caught:
        chart.compile_chart(plan, result, LIMITS, "")
    assert caught.value.code == "internal_error"


@pytest.mark.parametrize(
    "trace",
    [
        {"type": "scatter3d", "x": [1]},
        {"type": "scatter", "marker": {"color": "red"}},
        {"type": "scatter", "script": "x"},
    ],
)
def test_traces_outside_the_allow_list_are_refused(trace):
    x = ColumnSpec("x", N)
    with pytest.raises(QueryError) as caught:
        chart._spec("scatter", x, x, ["s"], [trace], "")
    assert caught.value.code == "internal_error"
