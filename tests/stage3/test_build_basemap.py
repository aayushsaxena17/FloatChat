"""The offline basemap builder (ADR-0062): exact rectangle clipping and recorded provenance."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import build_basemap as basemap  # noqa: E402

BOX = (0.0, 0.0, 10.0, 10.0)


def test_ring_inside_the_box_is_unchanged() -> None:
    ring = [(1.0, 1.0), (4.0, 1.0), (4.0, 4.0), (1.0, 4.0), (1.0, 1.0)]
    assert basemap.clip_polygon([ring], BOX) == [ring]


def test_ring_crossing_the_box_is_cut_at_the_edge() -> None:
    ring = [(5.0, 5.0), (15.0, 5.0), (15.0, 8.0), (5.0, 8.0), (5.0, 5.0)]
    [clipped] = basemap.clip_polygon([ring], BOX)
    assert max(lon for lon, _ in clipped) == 10.0 and min(lon for lon, _ in clipped) == 5.0
    assert clipped[0] == clipped[-1] and len(clipped) == 5


def test_ring_outside_the_box_is_dropped_with_its_holes() -> None:
    outer = [(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0), (20.0, 20.0)]
    hole = [(22.0, 22.0), (23.0, 22.0), (23.0, 23.0), (22.0, 23.0), (22.0, 22.0)]
    assert basemap.clip_polygon([outer, hole], BOX) == []


def test_hole_outside_the_box_is_dropped_but_the_outer_ring_kept() -> None:
    outer = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0), (5.0, 5.0)]
    hole = [(12.0, 12.0), (13.0, 12.0), (13.0, 13.0), (12.0, 13.0), (12.0, 12.0)]
    clipped = basemap.clip_polygon([outer, hole], BOX)
    assert len(clipped) == 1
    assert set(clipped[0]) == {(5.0, 5.0), (10.0, 5.0), (10.0, 10.0), (5.0, 10.0)}


def test_build_records_provenance_and_rounds(tmp_path: Path) -> None:
    source = tmp_path / "land.geojson"
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[1.23456, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0], [1.23456, 1.0]]],
                        [[[50.0, 50.0], [60.0, 50.0], [60.0, 60.0], [50.0, 60.0], [50.0, 50.0]]],
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [1, 1]},
            },
        ],
    }
    source.write_text(json.dumps(document))
    built = basemap.build(source, "https://example.invalid/land.geojson", BOX)
    assert built["properties"]["polygons"] == 1 and built["properties"]["points"] == 5
    assert built["properties"]["clip_box"] == {
        "west": 0.0,
        "south": 0.0,
        "east": 10.0,
        "north": 10.0,
    }
    assert len(built["properties"]["source_sha256"]) == 64
    assert list(built["features"][0]["geometry"]["coordinates"][0][0]) == [1.235, 1.0]


def test_committed_basemap_matches_its_recorded_counts() -> None:
    document = json.loads((ROOT / "apps/web/src/map/land.json").read_text())
    properties = document["properties"]
    assert properties["polygons"] == len(document["features"])
    assert properties["points"] == sum(
        len(ring) for feature in document["features"] for ring in feature["geometry"]["coordinates"]
    )
    box = properties["clip_box"]
    for feature in document["features"]:
        for ring in feature["geometry"]["coordinates"]:
            for lon, lat in ring:
                assert box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]
    assert "naturalearth" in properties["source"].lower().replace(" ", "")
