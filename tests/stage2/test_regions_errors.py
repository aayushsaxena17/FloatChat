"""Named-region fixture, error registry, and geography resolution (plan sections 4, 5.5 and 8)."""

import ast
import hashlib
import json
import math
import re
from pathlib import Path

import floatchat_core.query as query_package
import pytest
from floatchat_core.ingestion import planning
from floatchat_core.query import errors, geography
from floatchat_core.query.errors import REGISTRY, Detail, QueryError
from floatchat_core.query.plan import BoundingBox, NamedRegion, PointRadius
from floatchat_core.query.regions import FIXTURE, find_region, load_regions

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/migrations/versions/0016_query_access.sql"
Tile = planning.Tile
# One point inside each region, found by hand; (-100, 0) is outside every region.
INSIDE = {
    "Arabian Sea": (65, 15),
    "Bay of Bengal": (88, 15),
    "Laccadive Sea": (74, 8),
    "Andaman Sea": (95, 12),
    "Indian Ocean (IHO)": (70, -20),
    "Indian Ocean": (70, -20),
    "Southern Indian Ocean": (70, -45),
}


def polygons(wkt):
    """Rings of a MULTIPOLYGON text: a list of polygons, each a list of (x, y) rings."""
    assert wkt.startswith("MULTIPOLYGON(((") and wkt.endswith(")))")
    parts = wkt[len("MULTIPOLYGON(((") : -3].split(")),((")
    return [
        [
            [tuple(map(float, pair.split())) for pair in ring.split(",")]
            for ring in part.split("),(")
        ]
        for part in parts
    ]


def covers(wkt, point):
    """Even-odd ray casting; enough for interior points (boundary points are not used)."""
    x, y = point
    inside = False
    for polygon in polygons(wkt):
        for ring in polygon:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    inside = not inside
    return inside


def test_fixture_has_seven_unique_verified_regions():
    records = load_regions()
    assert len(records) == 7 and len({record.name for record in records}) == 7
    assert json.loads(FIXTURE.read_text())["schema"] == "named-regions-fixture-v1"
    for record in records:
        assert hashlib.sha256(record.wkt.encode()).hexdigest() == record.sha256
        assert re.fullmatch(r"[0-9a-f]{64}", record.sha256) and record.citation and record.version
    iho = [record for record in records if record.kind == "iho"]
    assert len(iho) == 5 and all(re.fullmatch(r"MRGID \d+", r.source_id or "") for r in iho)
    assert {record.kind for record in records} == {"iho", "operational"}
    operational = {r.name: r for r in records if r.kind == "operational"}
    assert {name: r.version for name, r in operational.items()} == {
        "Indian Ocean": "indian-ocean-v1",
        "Southern Indian Ocean": "southern-indian-ocean-floatchat-v1",
    }
    assert all(r.source == "floatchat" and r.source_id is None for r in operational.values())
    assert find_region("Arabian Sea") is records[0] and find_region("arabian sea") is None


def test_indian_ocean_is_the_stage_1_envelope_as_a_multipolygon():
    indian = find_region("Indian Ocean")
    assert indian.wkt == "MULTIPOLYGON(" + planning.WKT[len("POLYGON") :] + ")"
    assert indian.version == planning.GEOMETRY_VERSION
    assert (
        geography.ENVELOPE_WKT == planning.WKT and geography.ENVELOPE_VERSION == "indian-ocean-v1"
    )
    assert indian.bbox == geography.ENVELOPE == (20.0, -60.0, 120.0, 30.0)
    assert find_region("Southern Indian Ocean").bbox == (20.0, -60.0, 120.0, -30.0)


@pytest.mark.parametrize("record", load_regions(), ids=lambda record: record.name)
def test_region_geometry_agrees_with_its_record(record):
    shapes = polygons(record.wkt)
    points = [point for polygon in shapes for ring in polygon for point in ring]
    assert all(ring[0] == ring[-1] and len(ring) >= 4 for polygon in shapes for ring in polygon)
    assert len(points) == record.vertices
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    assert (min(xs), min(ys), max(xs), max(ys)) == record.bbox
    assert covers(record.wkt, INSIDE[record.name]) and not covers(record.wkt, (-100, 0))
    public = record.public()
    assert "wkt" not in public and public["sha256"] == record.sha256
    assert public["bbox"] == dict(zip(("west", "south", "east", "north"), record.bbox, strict=True))


def test_operational_regions_nest_inside_each_other():
    south, indian = find_region("Southern Indian Ocean"), find_region("Indian Ocean")
    assert covers(indian.wkt, (70, -45)) and covers(indian.wkt, (70, -20))
    assert covers(south.wkt, (70, -45)) and not covers(south.wkt, (70, -20))


def test_migration_carries_every_fixture_region_verbatim():
    sql = MIGRATION.read_text()
    assert sql.count("INSERT INTO app.named_region(") == len(load_regions())
    for record in load_regions():
        assert sql.count(record.wkt) == 1 and sql.count(record.sha256) == 1
        assert f"'{record.name}'" in sql and f"'{record.version}'" in sql


# ----- error registry ----------------------------------------------------------------------------
STATUS = {
    "plan_invalid": 422, "unknown_region": 422, "cost_over_budget": 422, "coverage_missing": 422,
    "not_found": 404, "invalid_cursor": 400, "invalid_parameter": 400, "payload_too_large": 413,
    "result_too_large": 422, "statement_timeout": 504, "execution_failed": 502,
    "internal_error": 500, "service_unavailable": 503,
}  # fmt: skip


def test_every_registered_code_has_an_http_status_and_fixed_text():
    assert STATUS.items() <= {code: status for code, (status, _) in REGISTRY.items()}.items()
    for code, (status, message) in REGISTRY.items():
        assert 400 <= status <= 599 and message.endswith(".")
        assert QueryError(code).status == status and QueryError(code).text == message
        assert QueryError(code).message is None and str(QueryError(code)) == code
    with pytest.raises(TypeError):
        REGISTRY["x"] = (200, "x")  # type: ignore[index]


def test_unregistered_codes_are_refused():
    for code in ("nope", "", "plan_valid", "unknown_variable", "PLAN_INVALID"):
        with pytest.raises(ValueError, match="unregistered error code"):
            QueryError(code)
    with pytest.raises(ValueError, match="unregistered detail code"):
        Detail("field", "nope", "message")
    with pytest.raises(ValueError, match="unregistered detail code"):
        Detail("field", "plan_invalid", "message")  # top-level codes are not detail codes
    with pytest.raises(AttributeError):
        Detail("a", "unknown_field", "m").field = "b"  # type: ignore[misc]


def test_plan_4_2_detail_codes_are_registered():
    required = {
        "unknown_field", "unknown_variable", "unknown_region", "unknown_function",
        "invalid_time_range", "invalid_depth_range", "invalid_geography", "unbounded_request",
        "disallowed_format", "cost_over_budget", "operation_variable_mismatch",
    }  # fmt: skip
    assert required <= errors.DETAIL_CODES


def test_error_envelope_shape():
    detail = Detail("operation.metrics.1", "unknown_function", "unknown metric or group key")
    error = QueryError("plan_invalid", [detail])
    assert error.details == (detail,) and error.text == REGISTRY["plan_invalid"][1]
    assert error.as_dict("abc-123") == {
        "error": {
            "code": "plan_invalid",
            "message": REGISTRY["plan_invalid"][1],
            "details": [
                {
                    "field": "operation.metrics.1",
                    "code": "unknown_function",
                    "message": "unknown metric or group key",
                }
            ],
            "correlation_id": "abc-123",
        }
    }
    custom = QueryError("execution_failed", message="Catalogue object key is malformed.")
    assert custom.as_dict("c")["error"]["message"] == "Catalogue object key is malformed."
    assert QueryError("not_found").as_dict("c")["error"]["details"] == []


def test_every_literal_code_raised_in_the_query_package_is_registered():
    seen = set()
    for path in Path(query_package.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", None))
            index = {"QueryError": 0, "Detail": 1}.get(name)
            if index is None or len(node.args) <= index:
                continue
            argument = node.args[index]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                registry = REGISTRY if name == "QueryError" else errors.DETAIL_CODES
                assert argument.value in registry, f"{path.name}:{node.lineno} {argument.value}"
                seen.add((name, argument.value))
    assert ("QueryError", "plan_invalid") in seen and ("Detail", "unbounded_request") in seen


# ----- geography ---------------------------------------------------------------------------------
def tiles(*boxes):
    return [(tile.west, tile.south) for tile in geography.envelope_tiles(boxes)]


def test_envelope_tiles_inside_straddling_and_outside():
    assert tiles((25, -55, 35, -45)) == [(20, -60), (20, -50), (30, -60), (30, -50)]
    assert tiles((25, -55, 26, -54)) == [(20, -60)]
    assert tiles((30, -50, 30, -50)) == [(30, -50)]  # a tile owns its west and south edges
    assert tiles((21, -59, 30, -51)) == [(20, -60), (30, -60)]  # east edge reaches the next tile
    assert tiles((15, -65, 25, -55)) == [(20, -60)]  # straddles the envelope; clipped to it
    assert tiles((0, 0, 10, 10)) == tiles((130, 0, 140, 10)) == tiles((50, -90, 60, -61)) == []
    assert tiles((15, 25, 25, 90)) == [(20, 20)]
    assert tiles((25, -55, 26, -54), (55, 5, 56, 6)) == [(20, -60), (50, 0)]  # union, sorted


def test_envelope_tiles_cover_the_whole_envelope():
    assert geography.envelope_tiles((geography.ENVELOPE,)) == geography.all_tiles()
    assert len(geography.all_tiles()) == 90 and all(
        isinstance(t, Tile) for t in geography.all_tiles()
    )


def test_the_outer_east_and_north_edges_belong_to_the_last_tile():
    assert tiles((110, 20, 120, 30)) == [(110, 20)]
    assert tiles((119.9, 29.9, 120, 30)) == [(110, 20)]
    assert tiles((20, -60, 20, -60)) == [(20, -60)]


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ((120, 30, 120, 30), [(110, 20)]),
        # Box edges are inclusive (ST_Covers on an envelope), so a box ending exactly on a
        # tile boundary also meets the neighbouring tile: a superset is the safe coverage set.
        ((120, 0, 130, 10), [(110, 0), (110, 10)]),
        ((50, 30, 60, 40), [(50, 20), (60, 20)]),
    ],
)
def test_boxes_starting_on_the_outer_edge_reach_the_last_tile(box, expected):
    assert tiles(box) == expected


def destination(longitude, latitude, bearing, distance_m):
    angular = distance_m / geography.EARTH_RADIUS_M
    lat1, lon1, theta = map(math.radians, (latitude, longitude, bearing))
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular) + math.cos(lat1) * math.sin(angular) * math.cos(theta)
    )
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lon2) + 540) % 360 - 180, math.degrees(lat2)


def test_point_radius_boxes_basic_pole_clamp_and_antimeridian_split():
    ((west, south, east, north),) = geography.point_radius_boxes(65, 15, 100_000)
    assert south < 15 < north and west < 65 < east and (east - west) > (north - south)
    assert (north - south) / 2 == pytest.approx(math.degrees(100_000 / geography.EARTH_RADIUS_M))
    assert geography.point_radius_boxes(0, 89.5, 100_000) == (
        (-180.0, pytest.approx(88.6007), 180.0, 90.0),
    )
    assert geography.point_radius_boxes(0, -89.5, 100_000) == (
        (-180.0, -90.0, 180.0, pytest.approx(-88.6007)),
    )
    assert geography.point_radius_boxes(0, 0, 10_000_000)[0][::2] == (-180.0, 180.0)
    east_side = geography.point_radius_boxes(179.5, 0, 100_000)
    assert len(east_side) == 2 and east_side[0][2] == 180.0 and east_side[1][0] == -180.0
    assert east_side[0][0] == pytest.approx(178.6006, abs=1e-3)
    assert east_side[1][2] == pytest.approx(-179.6006, abs=1e-3)
    west_side = geography.point_radius_boxes(-179.5, 0, 100_000)
    assert west_side[0][0] == pytest.approx(179.6006, abs=1e-3)
    assert west_side[1][2] == pytest.approx(-178.6006, abs=1e-3)


@pytest.mark.parametrize(
    ("longitude", "latitude", "radius_m"),
    [
        (65, 15, 250_000),
        (179.5, 0, 100_000),
        (-179.9, 40, 300_000),
        (0, 85, 500_000),
        (100, -75, 800_000),
    ],
)
def test_point_radius_boxes_contain_the_whole_circle(longitude, latitude, radius_m):
    boxes = geography.point_radius_boxes(longitude, latitude, radius_m)
    for bearing in range(0, 360, 10):
        x, y = destination(longitude, latitude, bearing, radius_m * 0.999)
        assert any(w - 1e-9 <= x <= e + 1e-9 and s - 1e-9 <= y <= n + 1e-9 for w, s, e, n in boxes)


def test_resolve_geography():
    arabian = geography.resolve_geography(NamedRegion(kind="named_region", value="Arabian Sea"))
    assert (arabian.kind, arabian.label, arabian.region) == (
        "named_region",
        "Arabian Sea",
        find_region("Arabian Sea"),
    )
    assert arabian.boxes == (arabian.region.bbox,)
    assert arabian.describe() == {
        "kind": "named_region",
        "name": "Arabian Sea",
        "version": arabian.region.version,
        "sha256": arabian.region.sha256,
        "clipped": False,
    }
    bbox = geography.resolve_geography(
        BoundingBox(kind="bbox", west=170, south=0, east=-170, north=10)
    )
    assert (
        bbox.label == "bbox"
        and len(bbox.boxes) == 2
        and bbox.describe()["boxes"][1]["west"] == -180.0
    )
    point = geography.resolve_geography(
        PointRadius(kind="point_radius", longitude=65, latitude=15, radius_km=250)
    )
    assert (point.radius_m, point.point) == (250_000.0, (65, 15)) and point.describe()[
        "radius_m"
    ] == 250_000.0
    assert point.boxes == geography.point_radius_boxes(65, 15, 250_000.0)


@pytest.mark.parametrize(
    "name", ["Atlantis", "", "arabian sea", "Arabian Sea ", "Аrabian Sea", "x'; --"]
)
def test_unknown_region_names_raise_unknown_region(name):
    with pytest.raises(QueryError) as caught:
        geography.resolve_geography(NamedRegion(kind="named_region", value=name or "?"))
    assert caught.value.code == "unknown_region" and caught.value.status == 422
