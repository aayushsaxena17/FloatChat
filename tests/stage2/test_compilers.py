"""SQL compilers without a database: fixed templates, bound values, injection fuzzing (plan 8)."""

import base64
import dataclasses
import json
import re
import uuid
from datetime import UTC, datetime

import pytest
from floatchat_core.query import compile_duckdb, compile_sql
from floatchat_core.query.errors import QueryError
from floatchat_core.query.geography import ResolvedGeography, resolve_geography
from floatchat_core.query.plan import decode_cursor, encode_cursor, validate_plan
from floatchat_core.query.regions import find_region
from sqlalchemy.dialects.postgresql.base import PGDialect

START, END = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)
PROFILE_ID = "00000000-0000-4000-8000-000000000101"
PAYLOADS = (
    "'; DROP TABLE app.argo_profile; --",
    "$$; SELECT pg_sleep(100); $$",
    'x" OR "1"="1',
    "Аrabian Sеa",  # Cyrillic homoglyphs
    "ＤＲＯＰ ＴＡＢＬＥ ‘; --",
    "/* x */ UNION SELECT password FROM pg_shadow",
    "\\'; COPY app.argo_profile TO PROGRAM 'id'; --",
)
BASE = {
    "time_range": {"start": START.isoformat(), "end": END.isoformat()},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "variables": ["temperature", "salinity"],
    "operation": {"kind": "profiles", "limit": 10},
}
BBOX = {"kind": "bbox", "west": 50.0, "south": 0.0, "east": 70.0, "north": 20.0}
ANTIMERIDIAN = dict(BBOX, west=170.0, east=-170.0)
POINT = {"kind": "point_radius", "longitude": 65.0, "latitude": 15.0, "radius_km": 250}
NEAREST = {"kind": "nearest", "longitude": 65.0, "latitude": 15.0, "radius_km": 100, "k": 5}


def aggregate(*, keys=("month",), metrics=("mean", "count"), unit="profile", **extra):
    return {
        "kind": "aggregate",
        "group_by": list(keys),
        "metrics": list(metrics),
        "unit": unit,
        **extra,
    }


def make(**changes):
    plan = validate_plan(BASE | changes)
    return plan, resolve_geography(plan.geography)


def compiled(statement):
    return statement.compile(dialect=PGDialect())


def text_of(statement):
    return compile_sql.render(statement)


def values_of(statement):
    """Every bound value, with the expanding IN lists flattened."""
    flat = []
    for value in compiled(statement).params.values():
        flat.extend(value if isinstance(value, list) else [value])
    return flat


def test_profiles_statement_for_a_named_region_is_half_open_and_keyset_paged():
    plan, geography = make()
    after = (datetime(2025, 1, 5, 6, tzinfo=UTC), PROFILE_ID)
    statement = compile_sql.profiles_statement(plan, geography, limit=10, after=after)
    text, params = text_of(statement), compiled(statement).params
    assert "ST_Covers(app.named_region.geometry, app.query_profile.position)" in text
    assert "app.named_region.name = %(name_1)s" in text and "FROM app.query_profile" in text
    assert "app.query_profile.source = %(source_1)s" in text and params["source_1"] == "argovis"
    assert "observed_at >= %(observed_at_1)s" in text and "observed_at < %(observed_at_2)s" in text
    assert "<=" not in text and "BETWEEN" not in text
    assert (params["observed_at_1"], params["observed_at_2"]) == (START, END)
    assert (params["name_1"], params["version_1"]) == ("Arabian Sea", geography.region.version)
    assert "(app.query_profile.observed_at, app.query_profile.id) < (" in text
    assert "ORDER BY app.query_profile.observed_at DESC, app.query_profile.id DESC" in text
    assert 11 in values_of(statement) and after[0] in values_of(statement)
    assert "(app.query_profile.observed_at, app.query_profile.id) <" not in text_of(
        compile_sql.profiles_statement(plan, geography, limit=10)
    )


def test_bbox_compiles_to_one_or_two_or_ed_envelopes():
    plain, geography = make(geography=BBOX)
    text = text_of(compile_sql.profiles_statement(plain, geography, limit=5))
    assert text.count("ST_Covers(ST_MakeEnvelope(") == 1 and " OR " not in text
    assert "app.named_region" not in text and "ST_DWithin" not in text
    values = values_of(compile_sql.profiles_statement(plain, geography, limit=5))
    assert {50.0, 0.0, 70.0, 20.0, 4326} <= set(values)

    crossing, geography = make(geography=ANTIMERIDIAN)
    statement = compile_sql.profiles_statement(crossing, geography, limit=5)
    text = text_of(statement)
    assert text.count("ST_Covers(ST_MakeEnvelope(") == 2
    assert re.search(
        r"ST_Covers\(ST_MakeEnvelope\((%\(\w+\)s(, )?)+\), app\.query_profile\.position\) OR ST_Covers",
        text,
    )
    assert {170.0, 180.0, -180.0, -170.0} <= set(values_of(statement))


def test_depth_filter_uses_policy_selected_pressure_in_an_exists_over_levels():
    plan, geography = make(depth_dbar={"min": 7.5, "max": 321.0}, qc_policy="mode_selected")
    statement = compile_sql.profiles_statement(plan, geography, limit=5)
    text = text_of(statement)
    assert re.search(r"EXISTS \(SELECT \*\s+FROM app\.query_measurement", text)
    assert "app.query_measurement.pressure_data_mode IN" in text and "pressure_qc" not in text
    assert re.search(r"ELSE NULL END BETWEEN %\(param_1\)s AND %\(param_2\)s", text)
    assert {7.5, 321.0} <= set(values_of(statement))
    science, geography = make(depth_dbar={"min": 0, "max": 50})
    assert "pressure_adjusted_qc" in text_of(
        compile_sql.profiles_statement(science, geography, limit=1)
    )


def test_nearest_statement_prefilters_with_dwithin_and_orders_by_geodesic_distance():
    plan, geography = make(geography=POINT, operation=NEAREST, depth_dbar={"min": 0, "max": 10})
    statement = compile_sql.nearest_statement(plan, geography)
    text = text_of(statement)
    cast_position = "CAST(app.query_profile.position AS geography)"
    cast_point = "CAST(ST_SetSRID(ST_MakePoint(%(ST_MakePoint_1)s, %(ST_MakePoint_2)s)"
    assert f"ST_DWithin({cast_position}, {cast_point}" in text
    assert f"ST_Distance({cast_position}, {cast_point}" in text and "AS distance_m" in text
    assert "ORDER BY distance_m, app.query_profile.id" in text and "EXISTS" in text
    assert "ST_Covers" not in text.split("EXISTS")[0]
    params = compiled(statement).params
    assert params["ST_DWithin_1"] == 100_000.0 and 5 in params.values()
    assert (params["ST_MakePoint_1"], params["ST_MakePoint_2"]) == (65.0, 15.0)
    point_text = text_of(compile_sql.profiles_statement(*make(geography=POINT), limit=3))
    assert "ST_DWithin(CAST(app.query_profile.position AS geography)" in point_text


@pytest.mark.parametrize("unit", ["profile", "measurement"])
@pytest.mark.parametrize(
    ("metric", "fragment"),
    [
        ("mean", "avg("),
        ("count", "count("),
        ("min", "min("),
        ("max", "max("),
        ("stddev", "stddev_samp("),
        ("median", "percentile_cont(%(percentile_cont_1)s) WITHIN GROUP (ORDER BY"),
    ],
)
def test_aggregate_metrics(unit, metric, fragment):
    plan, geography = make(operation=aggregate(metrics=(metric,), unit=unit))
    statement = compile_sql.aggregate_statement(plan, geography, max_rows=100)
    text = text_of(statement)
    assert (
        fragment in text and f"AS temperature_{metric}" in text and f"AS salinity_{metric}" in text
    )
    assert ("per_profile" in text) == (unit == "profile")
    assert 0.5 in values_of(statement) or metric != "median"
    assert 101 in values_of(statement)


def test_profile_unit_aggregates_per_profile_first_and_counts_profiles():
    plan, geography = make(operation=aggregate(metrics=("mean", "count")))
    text = text_of(compile_sql.aggregate_statement(plan, geography, max_rows=10))
    assert re.search(r"FROM \(SELECT app\.query_profile\.id AS profile_id, ", text)
    assert ") AS per_profile GROUP BY per_profile.key_month" in text
    assert "avg(CASE WHEN" in text and "count(per_profile.temperature_value)" in text
    assert "GROUP BY app.query_profile.id, to_char(" in text
    assert "ORDER BY per_profile.key_month" in text
    measurement, geography = make(operation=aggregate(unit="measurement", metrics=("count",)))
    flat = text_of(compile_sql.aggregate_statement(measurement, geography, max_rows=10))
    assert "per_profile" not in flat and "count(CASE WHEN" in flat
    assert "GROUP BY to_char(timezone(" in flat and "ORDER BY to_char(" in flat


@pytest.mark.parametrize(
    ("key", "fragment", "bound"),
    [
        ("month", "to_char(timezone(%(timezone_1)s, app.query_profile.observed_at)", "YYYY-MM"),
        ("day", "to_char(timezone(%(timezone_1)s, app.query_profile.observed_at)", "YYYY-MM-DD"),
        ("profile", "CAST(app.query_profile.id AS TEXT)", None),
        ("float", "app.query_profile.platform_number", None),
    ],
)
def test_group_keys_use_fixed_expressions(key, fragment, bound):
    plan, geography = make(operation=aggregate(keys=(key,)))
    statement = compile_sql.aggregate_statement(plan, geography, max_rows=10)
    assert fragment in text_of(statement) and f"AS {key}" in text_of(statement)
    assert bound is None or (bound in values_of(statement) and "UTC" in values_of(statement))


def test_depth_bin_key_floors_the_selected_pressure():
    plan, geography = make(
        operation=aggregate(keys=("depth_bin",), depth_bin_size=25, unit="measurement")
    )
    statement = compile_sql.aggregate_statement(plan, geography, max_rows=10)
    assert "floor(CASE WHEN" in text_of(statement) and "25" not in text_of(statement)
    assert values_of(statement).count(25) >= 2  # floor(p / size) * size


def test_region_key_is_a_bound_label_and_never_grouped():
    plan, geography = make(operation=aggregate(keys=("month", "region"), unit="measurement"))
    statement = compile_sql.aggregate_statement(plan, geography, max_rows=10)
    text, params = text_of(statement), compiled(statement).params
    name = next(
        key for key, value in params.items() if value == "Arabian Sea" and key.startswith("param")
    )
    assert f"%({name})s AS region" in text and name not in text.split("GROUP BY")[1]
    alone, geography = make(
        operation=aggregate(keys=("region",), unit="measurement", metrics=("mean",))
    )
    assert "GROUP BY" not in text_of(compile_sql.aggregate_statement(alone, geography, max_rows=10))
    # With the profile unit the constant is carried through, never grouped inside the subquery.
    inner, geography = make(operation=aggregate(keys=("region",), metrics=("mean",)))
    flat = text_of(compile_sql.aggregate_statement(inner, geography, max_rows=10))
    assert flat.count("GROUP BY") == 2 and flat.split("GROUP BY")[1].strip().startswith(
        "app.query_profile.id"
    )
    assert "AS key_region" in flat and "GROUP BY app.query_profile.id)" in flat.replace("\n", " ")


def test_floats_trajectory_levels_and_support_statements():
    geography = resolve_geography(validate_plan(BASE).geography)
    floats = compile_sql.floats_statement(
        START, END, geography, limit=7, after="5900001", platform_number="5900002"
    )
    text = text_of(floats)
    assert "count(*) AS profile_count" in text and "min(app.query_profile.cycle_number)" in text
    assert (
        "(array_agg(ST_X(app.query_profile.position) ORDER BY app.query_profile.observed_at DESC))["
        in text
    )
    assert "GROUP BY app.query_profile.platform_number, app.query_profile.source" in text
    assert (
        "platform_number = %(platform_number_1)s" in text
        and "platform_number > %(platform_number_2)s" in text
    )
    assert {"5900001", "5900002", 8} <= set(values_of(floats))
    assert "ST_Covers" not in text_of(compile_sql.floats_statement(START, END, None, limit=1))

    trajectory = compile_sql.trajectory_statement("5900001", START, END, limit=4)
    assert "platform_number = %(platform_number_1)s" in text_of(trajectory) and 5 in values_of(
        trajectory
    )
    assert "ORDER BY app.query_profile.observed_at DESC, app.query_profile.id DESC" in text_of(
        trajectory
    )

    identifier = uuid.UUID(PROFILE_ID)

    def levels(policy):
        statement = compile_sql.levels_statement(
            identifier, START.date(), policy=policy, depth=None, limit=9
        )
        return text_of(statement)

    adjusted, raw = levels("science_ready"), levels("raw")
    assert "temperature_adjusted_qc" in adjusted and "temperature_error" not in adjusted
    assert "temperature_error" in raw and "CASE WHEN" not in raw
    assert (
        adjusted.rstrip().endswith("LIMIT %(param_1)s")
        and "ORDER BY app.query_measurement.level_index" in adjusted
    )
    assert "is_current" in text_of(compile_sql.regions_statement())
    tiles = compile_sql.region_tiles_statement("Arabian Sea", "v1", [(20, 0), (30, 0)])
    assert "ST_Intersects(app.named_region.geometry, ST_MakeEnvelope(tiles.west" in text_of(tiles)
    assert {20, 30, 0, "Arabian Sea", "v1"} <= set(values_of(tiles))
    slots = compile_sql.profile_slot_statement(validate_plan(BASE), geography, ["a"])
    assert "CAST(app.query_profile.id AS TEXT) AS profile_id" in text_of(slots)
    assert "content_hash AS profile_hash" in text_of(slots)


def hostile_geography(payload):
    """A resolved region whose name, version and label are all attacker text."""
    region = dataclasses.replace(find_region("Arabian Sea"), name=payload, version=payload)
    return ResolvedGeography("named_region", payload, (region.bbox,), region=region)


@pytest.mark.parametrize("payload", PAYLOADS)
def test_hostile_text_is_bound_and_never_rendered(payload):
    plan = validate_plan(BASE)
    hostile = hostile_geography(payload)

    def grouped(unit):
        return validate_plan(BASE | {"operation": aggregate(keys=("month", "region"), unit=unit)})

    statements = [
        compile_sql.profiles_statement(plan, hostile, limit=5),
        compile_sql.aggregate_statement(grouped("profile"), hostile, max_rows=5),
        compile_sql.aggregate_statement(grouped("measurement"), hostile, max_rows=5),
        compile_sql.floats_statement(START, END, hostile, limit=5, after=payload),
        compile_sql.floats_statement(START, END, None, limit=5, platform_number=payload),
        compile_sql.trajectory_statement(payload, START, END, limit=5),
        compile_sql.region_tiles_statement(payload, payload, [(20, 0)]),
        compile_sql.profile_slot_statement(plan, hostile, [payload]),
    ]
    for statement in statements:
        assert payload not in text_of(statement)
        assert payload in values_of(statement)


@pytest.mark.parametrize("payload", PAYLOADS)
def test_hostile_plan_text_is_refused_before_any_compiler(payload):
    plan = validate_plan(BASE | {"geography": {"kind": "named_region", "value": payload}})
    with pytest.raises(QueryError) as unknown:
        resolve_geography(plan.geography)
    assert unknown.value.code == "unknown_region"
    assert payload not in json.dumps(unknown.value.as_dict("c")) and find_region(payload) is None
    operation = {"kind": "profiles", "limit": 5, "cursor": payload}
    cursor = validate_plan(BASE | {"operation": operation}).operation.cursor
    with pytest.raises(QueryError) as invalid:
        decode_cursor(cursor, "profile")
    assert invalid.value.code == "invalid_cursor"
    # A well-formed float cursor may carry any text; it is only ever a bound comparison value.
    after = decode_cursor(encode_cursor("float", platform_number=payload), "float")
    statement = compile_sql.floats_statement(
        START, END, None, limit=1, after=after["platform_number"]
    )
    assert payload not in text_of(statement) and payload in values_of(statement)


def test_profile_cursor_with_a_non_uuid_id_is_an_invalid_cursor():
    document = {"kind": "profile", "t": START.isoformat(), "id": "x" * 36}
    cursor = base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")
    with pytest.raises(QueryError) as invalid:
        decode_cursor(cursor, "profile")
    assert invalid.value.code == "invalid_cursor"


@pytest.mark.parametrize("unit", ["profile", "measurement"])
def test_duckdb_statement_uses_named_parameters_only(unit):
    operation = aggregate(
        keys=("month", "depth_bin", "region"),
        metrics=("mean", "median", "stddev"),
        unit=unit,
        depth_bin_size=25,
    )
    plan = validate_plan(BASE | {"operation": operation, "depth_dbar": {"min": 7.5, "max": 321.0}})
    texts = set()
    for label in ("Arabian Sea", *PAYLOADS):
        statement = compile_duckdb.aggregate_statement(plan, label=label, max_rows=500)
        sql = statement.sql
        texts.add(sql)
        assert set(re.findall(r"\$([A-Za-z_]\w*)", sql)) == set(statement.parameters)
        assert "?" not in sql and label not in sql and "321" not in sql and "7.5" not in sql
        assert statement.parameters == {
            "row_limit": 501,
            "depth_bin_size": 25,
            "region_label": label,
            "depth_min": 7.5,
            "depth_max": 321.0,
        }
        assert statement.columns[:3] == ("month", "depth_bin", "region")
        assert statement.columns[3:5] == ("temperature_mean", "temperature_median")
        assert ("per_profile" in sql) == (unit == "profile")
        assert "quantile_cont(" in sql and "stddev_samp(" in sql and "LIMIT $row_limit" in sql
    assert len(texts) == 1  # the template is fixed; only the parameters vary
    sql = texts.pop()
    if unit == "measurement":
        assert "$region_label AS region" in sql and "$region_label" not in sql.split("GROUP BY")[1]
