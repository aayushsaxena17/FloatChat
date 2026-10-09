"""Query plan validation, normalisation, hashing and keyset cursors (plan sections 4 and 5.1)."""

import base64
import copy
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import (
    PLAN_SCHEMA,
    BoundingBox,
    decode_cursor,
    encode_cursor,
    validate_plan,
)

LIMITS = QueryLimits()
IST = timezone(timedelta(hours=5, minutes=30))
DELETE = object()
PROFILE_ID = "00000000-0000-4000-8000-000000000101"
BASE = {
    "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "variables": ["temperature", "salinity"],
    "operation": {"kind": "profiles", "limit": 10},
}
AGG = {"kind": "aggregate", "group_by": ["month"], "metrics": ["mean", "count"]}
BBOX = {"kind": "bbox", "west": 50.0, "south": 0.0, "east": 70.0, "north": 20.0}
NEAREST = {"kind": "nearest", "longitude": 65.0, "latitude": 15.0, "radius_km": 100, "k": 5}
POINT = {"kind": "point_radius", "longitude": 0, "latitude": 0, "radius_km": 5}

CHART = {"presentation": {"kind": "line_chart"}}


def payload(**changes):
    """The base plan with changes; ``a__b`` addresses a nested key and ``DELETE`` removes it."""
    document = copy.deepcopy(BASE)
    for path, value in changes.items():
        parts = path.split("__")
        target = document
        for part in parts[:-1]:
            target = target[part]
        if value is DELETE:
            del target[parts[-1]]
        else:
            target[parts[-1]] = value
    return document


def span(days):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return {"start": start.isoformat(), "end": (start + timedelta(days=days)).isoformat()}


def rejection(document, limits=LIMITS):
    with pytest.raises(QueryError) as caught:
        validate_plan(document, limits)
    assert caught.value.code == "plan_invalid" and caught.value.status == 422
    return {(detail.field, detail.code) for detail in caught.value.details}


def one(field, code):
    return {(field, code)}


def geo(base=BBOX, **changes):
    return {"geography": dict(base, **changes)}


def op(base=AGG, **changes):
    return {"operation": dict(base, **changes)}


def depth(low, high):
    return {"depth_dbar": {"min": low, "max": high}}


def pres(kind, **changes):
    return {"presentation": {"kind": kind, **changes}}


TIME, DEPTH, GEO, UNBOUNDED = (
    "invalid_time_range",
    "invalid_depth_range",
    "invalid_geography",
    "unbounded_request",
)
UNKNOWN, MISSING, VALUE, FIELD = (
    "unknown_function",
    "missing_field",
    "invalid_value",
    "unknown_field",
)
MISMATCH = "operation_variable_mismatch"
KIND = "presentation.kind"
# id: (changes, expected {(field, code)}); one entry per rejection of plan section 4.2.
REJECTIONS = {
    "unknown_field_top": ({"extra": 1}, one("extra", FIELD)),
    "unknown_field_time_range": ({"time_range__zone": "UTC"}, one("time_range.zone", FIELD)),
    "unknown_field_operation": ({"operation__nope": 1}, one("operation.nope", FIELD)),
    "unknown_field_geography": ({"geography__radius": 1}, one("geography.radius", FIELD)),
    "unknown_field_presentation": (pres("table", colour="red"), one("presentation.colour", FIELD)),
    "unknown_variable": (
        {"variables": ["temperature", "oxygen"]},
        one("variables.1", "unknown_variable"),
    ),
    "unknown_metric": (op(metrics=["mean", "mode"]), one("operation.metrics.1", UNKNOWN)),
    "unknown_group_key": (op(group_by=["month", "galaxy"]), one("operation.group_by.1", UNKNOWN)),
    "disallowed_format": (pres("pie"), one(KIND, "disallowed_format")),
    "qc_policy": ({"qc_policy": "gold"}, one("qc_policy", VALUE)),
    "dataset": ({"dataset": "gdac"}, one("dataset", VALUE)),
    "no_variables": ({"variables": []}, one("variables", VALUE)),
    "missing_metrics": ({"operation": {"kind": "aggregate"}}, one("operation.metrics", MISSING)),
    "bad_geography_kind": ({"geography": {"kind": "x"}}, one("geography", VALUE)),
    "naive_start": ({"time_range__start": "2025-01-01T00:00:00"}, one("time_range.start", TIME)),
    "naive_end": ({"time_range__end": "2025-02-01T00:00:00"}, one("time_range.end", TIME)),
    "unparseable_start": ({"time_range__start": "yesterday"}, one("time_range.start", TIME)),
    "start_after_end": (
        {"time_range": {"start": "2025-02-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"}},
        one("time_range", TIME),
    ),
    "start_equals_end_other_offset": (
        {"time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-01-01T05:30:00+05:30"}},
        one("time_range", TIME),
    ),
    "span_over_limit": ({"time_range": span(367)}, one("time_range", UNBOUNDED)),
    "depth_min_over_max": (depth(100, 50), one("depth_dbar", DEPTH)),
    "depth_min_equals_max": (depth(50, 50), one("depth_dbar", DEPTH)),
    "depth_over_12000": (depth(0, 12001), one("depth_dbar.max", DEPTH)),
    "depth_negative": (depth(-1, 10), one("depth_dbar.min", DEPTH)),
    "depth_max_zero": (depth(0, 0), one("depth_dbar.max", DEPTH)),
    "depth_max_missing": ({"depth_dbar": {"min": 5}}, one("depth_dbar.max", MISSING)),
    "bbox_south_over_north": (geo(south=20.0, north=10.0), one("geography", GEO)),
    "bbox_south_equals_north": (geo(south=10.0, north=10.0), one("geography", GEO)),
    "bbox_west_equals_east": (geo(east=50.0), one("geography", GEO)),
    "bbox_west_0_360": (geo(west=200.0), one("geography.west", GEO)),
    "bbox_east_0_360": (geo(east=300.0), one("geography.east", GEO)),
    "bbox_north_91": (geo(north=91.0), one("geography.north", GEO)),
    "point_latitude_91": (geo(POINT, latitude=91), one("geography.latitude", GEO)),
    "point_radius_over_limit": (geo(POINT, radius_km=2000.5), one("geography.radius_km", GEO)),
    "point_radius_zero": (geo(POINT, radius_km=0), one("geography.radius_km", GEO)),
    "profiles_without_limit": ({"operation__limit": DELETE}, one("operation.limit", UNBOUNDED)),
    "profiles_over_page_size": (
        {"operation__limit": LIMITS.page_size + 1},
        one("operation.limit", UNBOUNDED),
    ),
    "aggregate_over_31_days_ungrouped": (
        op(group_by=[]) | {"time_range": span(40)},
        one("operation.group_by", UNBOUNDED),
    ),
    "aggregate_over_31_days_float_key": (
        op(group_by=["float"]) | {"time_range": span(40)},
        one("operation.group_by", UNBOUNDED),
    ),
    "nearest_k": (op(NEAREST, k=101), one("operation.k", UNBOUNDED)),
    "nearest_radius": (op(NEAREST, radius_km=2001), one("operation.radius_km", GEO)),
    "no_metrics": (op(metrics=[]), one("operation.metrics", UNBOUNDED)),
    "repeated_metric": (op(metrics=["mean", "mean"]), one("operation.metrics", VALUE)),
    "depth_bin_without_size": (op(group_by=["depth_bin"]), one("operation.depth_bin_size", VALUE)),
    "ts_diagram_without_salinity": (
        {"variables": ["temperature"]} | pres("ts_diagram"),
        one(KIND, MISMATCH),
    ),
    "map_with_aggregate": (op() | pres("map"), one(KIND, MISMATCH)),
    "raw_with_aggregate": (op() | {"qc_policy": "raw"}, one("qc_policy", MISMATCH)),
    "line_chart_without_month_or_day": (op(group_by=["float"]) | CHART, one(KIND, MISMATCH)),
    "profile_plot_with_aggregate": (op() | pres("profile_plot"), one(KIND, MISMATCH)),
    "histogram_with_profiles": (pres("histogram"), one(KIND, MISMATCH)),
    "nearest_with_ts_diagram": (op(NEAREST) | pres("ts_diagram"), one(KIND, MISMATCH)),
    "bins_without_histogram": (op() | pres("table", bins=10), one("presentation.bins", VALUE)),
    "bins_over_limit": (op() | pres("histogram", bins=201), one("presentation.bins", UNBOUNDED)),
}


def test_base_payloads_validate():
    plan = validate_plan(BASE)
    assert plan.qc_policy == "science_ready" and plan.presentation.kind == "table"
    assert validate_plan(payload(operation=AGG, **CHART))
    assert validate_plan(payload(geography=BBOX, operation=NEAREST, presentation={"kind": "map"}))
    assert validate_plan(payload(geography=dict(BBOX, west=170.0, east=-170.0)))
    assert validate_plan(payload(depth_dbar={"min": 0, "max": 12000}))
    assert validate_plan(payload(operation={"kind": "profiles", "limit": LIMITS.page_size}))


@pytest.mark.parametrize(("changes", "expected"), REJECTIONS.values(), ids=list(REJECTIONS))
def test_rejections(changes, expected):
    assert rejection(payload(**changes)) == expected


def test_span_limit_is_inclusive_and_follows_the_limits_object():
    assert validate_plan(payload(time_range=span(LIMITS.time_span_days)))
    assert rejection(payload(time_range=span(11)), QueryLimits(time_span_days=10)) == one(
        "time_range", "unbounded_request"
    )


@pytest.mark.parametrize("key", ["month", "day", "profile"])
def test_time_keys_bound_a_long_aggregate(key):
    assert validate_plan(payload(operation=dict(AGG, group_by=[key]), time_range=span(300)))
    assert validate_plan(payload(operation=dict(AGG, group_by=[]), time_range=span(31)))


def test_every_violation_is_reported_together():
    document = payload(
        time_range={"start": "2025-02-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
        depth_dbar={"min": 9, "max": 3},
        operation={"kind": "profiles"},
    )
    assert rejection(document) == {
        ("time_range", "invalid_time_range"),
        ("depth_dbar", "invalid_depth_range"),
        ("operation.limit", "unbounded_request"),
    }


@pytest.mark.parametrize("document", [None, [], "plan", 7])
def test_non_object_payload(document):
    assert rejection(document) == one("plan", "invalid_value")


def test_union_tags_never_appear_in_detail_paths():
    tags = {"aggregate", "profiles", "nearest", "named_region", "bbox", "point_radius"}
    for operation in (
        dict(AGG, metrics=["mean", "mode"], group_by=["nope"]),
        {"kind": "aggregate", "extra": 1, "metrics": ["mean"]},
        {"kind": "profiles", "limit": 0, "cursor": 5},
        dict(NEAREST, k=0, extra=1),
    ):
        for geography in (
            {"kind": "named_region", "value": ""},
            dict(BBOX, west=999.0),
            dict(POINT, radius_km=-1, extra=1),
        ):
            with pytest.raises(QueryError) as caught:
                validate_plan(payload(operation=operation, geography=geography))
            assert caught.value.details
            for detail in caught.value.details:
                assert not tags & set(detail.field.split("."))
    assert rejection(payload(operation=dict(AGG, metrics=["mean", "x"]))) == one(
        "operation.metrics.1", "unknown_function"
    )


def test_canonical_normalises_to_utc_z_and_orders_variables():
    plan = validate_plan(
        payload(
            time_range={"start": "2025-01-01T05:30:00+05:30", "end": "2025-01-31T20:00:00-04:00"},
            variables=["salinity", "pressure", "temperature", "salinity"],
        )
    )
    document = plan.canonical()
    assert document["time_range"] == {
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-02-01T00:00:00Z",
    }
    assert document["variables"] == ["temperature", "salinity", "pressure"]
    assert plan.ordered_variables == ("temperature", "salinity", "pressure")
    assert document["plan_schema"] == PLAN_SCHEMA == "stage2-plan-v1"
    assert (document["dataset"], document["qc_policy"]) == ("core", "science_ready")
    assert document["presentation"]["kind"] == "table"
    assert document["operation"] == {"kind": "profiles", "limit": 10, "cursor": None}
    json.dumps(document)


def test_canonical_form_revalidates_to_the_same_plan():
    plan = validate_plan(payload(operation=AGG, variables=["salinity", "temperature"]))
    document = plan.canonical()
    assert document.pop("plan_schema") == PLAN_SCHEMA
    again = validate_plan(document)
    assert again.canonical() | {"plan_schema": PLAN_SCHEMA} == plan.canonical()
    assert again.plan_sha256 == plan.plan_sha256


def test_plan_sha256_is_stable_across_key_order_and_timezone_spelling():
    reference = validate_plan(payload(operation=AGG))
    reordered = dict(reversed(list(payload(operation=AGG).items())))
    reordered["time_range"] = {"end": "2025-02-01T00:00:00+00:00", "start": "2025-01-01T00:00:00Z"}
    reordered["variables"] = ["salinity", "temperature"]
    offset = payload(
        operation=AGG,
        time_range={"start": "2025-01-01T01:00:00+01:00", "end": "2025-02-01T01:00:00+01:00"},
    )
    for variant in (reordered, offset):
        assert validate_plan(variant).plan_sha256 == reference.plan_sha256
    assert len(reference.plan_sha256) == 64 and int(reference.plan_sha256, 16) >= 0
    changed = validate_plan(payload(operation=dict(AGG, metrics=["mean"])))
    assert changed.plan_sha256 != reference.plan_sha256


def test_bounding_box_envelopes():
    plain = BoundingBox(kind="bbox", west=50, south=-5, east=70, north=20)
    assert not plain.crosses_antimeridian
    assert plain.envelopes() == ((50, -5, 70, 20),)
    crossing = BoundingBox(kind="bbox", west=170, south=-5, east=-170, north=20)
    assert crossing.crosses_antimeridian
    assert crossing.envelopes() == ((170, -5, 180.0, 20), (-180.0, -5, -170, 20))


def raw_cursor(document):
    text = document if isinstance(document, str) else json.dumps(document)
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_cursor_round_trip():
    moment = datetime(2025, 3, 5, 12, 30, tzinfo=UTC)
    cursor = encode_cursor("profile", t=moment.astimezone(IST), id=PROFILE_ID)
    assert "=" not in cursor and len(cursor) <= 512
    assert decode_cursor(cursor, "profile") == {"t": moment, "id": PROFILE_ID}
    assert decode_cursor(encode_cursor("float", platform_number="5900001"), "float") == {
        "platform_number": "5900001"
    }


def test_encode_cursor_rejects_wrong_fields():
    with pytest.raises(ValueError, match="cursor fields"):
        encode_cursor("profile", t=datetime.now(UTC))
    with pytest.raises(ValueError, match="cursor fields"):
        encode_cursor("float", platform_number="1", extra=2)


GOOD_PROFILE = {"kind": "profile", "t": "2025-03-05T12:30:00+00:00", "id": PROFILE_ID}
TAMPERED = {
    "empty": ("", "profile"),
    "not_base64": ("!!!!", "profile"),
    "not_json": (raw_cursor("hello"), "profile"),
    "json_list": (raw_cursor("[1, 2]"), "profile"),
    "wrong_kind": (encode_cursor("float", platform_number="1"), "profile"),
    "extra_key": (raw_cursor(dict(GOOD_PROFILE, extra="x")), "profile"),
    "missing_key": (raw_cursor({"kind": "profile", "t": GOOD_PROFILE["t"]}), "profile"),
    "naive_timestamp": (raw_cursor(dict(GOOD_PROFILE, t="2025-03-05T12:30:00")), "profile"),
    "bad_timestamp": (raw_cursor(dict(GOOD_PROFILE, t="soon")), "profile"),
    "non_string_value": (raw_cursor(dict(GOOD_PROFILE, id=7)), "profile"),
    "short_id": (raw_cursor(dict(GOOD_PROFILE, id="abc")), "profile"),
    "empty_value": (raw_cursor({"kind": "float", "platform_number": ""}), "float"),
    "long_platform": (raw_cursor({"kind": "float", "platform_number": "9" * 129}), "float"),
    "overlong": (raw_cursor(dict(GOOD_PROFILE, id="x" * 600)), "profile"),
    "injection": (
        raw_cursor(dict(GOOD_PROFILE, id="'; DROP TABLE app.argo_profile; --")),
        "profile",
    ),
}


@pytest.mark.parametrize(("cursor", "kind"), TAMPERED.values(), ids=list(TAMPERED))
def test_tampered_cursor_is_invalid(cursor, kind):
    with pytest.raises(QueryError) as caught:
        decode_cursor(cursor, kind)
    assert caught.value.code == "invalid_cursor" and caught.value.status == 400
