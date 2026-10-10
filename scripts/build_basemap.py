"""Clip a Natural Earth land GeoJSON to the FloatChat envelope for the offline basemap (ADR-0062).

    uv run --all-packages --frozen python scripts/build_basemap.py <ne_50m_land.geojson> \
        --source-url <url> -o apps/web/src/map/land.json

Natural Earth is public domain (https://www.naturalearthdata.com/about/terms-of-use/). The
output records the source URL, the SHA-256 of the downloaded file, the clip box and the counts
so the committed file can be reproduced; nothing is fetched by this script or by any test.

Clipping is Sutherland-Hodgman against the rectangle (exact for polygon rings against a convex
window); coordinates are rounded to three decimals (about 100 m), which is below the 1:50m
source resolution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

Point = tuple[float, float]
Ring = list[Point]
DEFAULT_BOX = (10.0, -65.0, 130.0, 35.0)  # west, south, east, north


def _clip_ring(ring: Ring, box: tuple[float, float, float, float]) -> Ring:
    west, south, east, north = box
    edges = (
        (lambda p: p[0] >= west, lambda a, b: _cross_x(a, b, west)),
        (lambda p: p[0] <= east, lambda a, b: _cross_x(a, b, east)),
        (lambda p: p[1] >= south, lambda a, b: _cross_y(a, b, south)),
        (lambda p: p[1] <= north, lambda a, b: _cross_y(a, b, north)),
    )
    output = list(ring)
    for inside, intersect in edges:
        if not output:
            return []
        points, output = output, []
        previous = points[-1]
        for current in points:
            if inside(current):
                if not inside(previous):
                    output.append(intersect(previous, current))
                output.append(current)
            elif inside(previous):
                output.append(intersect(previous, current))
            previous = current
    return output


def _cross_x(a: Point, b: Point, x: float) -> Point:
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _cross_y(a: Point, b: Point, y: float) -> Point:
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def _tidy(ring: Ring, decimals: int) -> Ring:
    rounded: Ring = []
    for lon, lat in ring:
        point = (round(lon, decimals), round(lat, decimals))
        if not rounded or rounded[-1] != point:
            rounded.append(point)
    if rounded and rounded[0] != rounded[-1]:
        rounded.append(rounded[0])
    return rounded if len(rounded) >= 4 else []


def clip_polygon(
    rings: list[Ring], box: tuple[float, float, float, float], decimals: int = 3
) -> list[Ring]:
    """Clip an outer ring and its holes; an emptied outer ring drops the polygon."""
    outer = _tidy(_clip_ring(rings[0], box), decimals)
    if not outer:
        return []
    holes = [_tidy(_clip_ring(hole, box), decimals) for hole in rings[1:]]
    return [outer, *[hole for hole in holes if hole]]


def clip_collection(
    document: dict[str, Any], box: tuple[float, float, float, float], decimals: int = 3
) -> list[list[Ring]]:
    polygons: list[list[Ring]] = []
    for feature in document["features"]:
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            candidates = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            candidates = geometry["coordinates"]
        else:
            continue
        for rings in candidates:
            clipped = clip_polygon([[tuple(p) for p in ring] for ring in rings], box, decimals)
            if clipped:
                polygons.append(clipped)
    return polygons


def build(
    source: Path, source_url: str, box: tuple[float, float, float, float], decimals: int = 3
) -> dict[str, Any]:
    payload = source.read_bytes()
    polygons = clip_collection(json.loads(payload), box, decimals)
    return {
        "type": "FeatureCollection",
        "properties": {
            "name": "Natural Earth land, clipped for FloatChat (ADR-0062)",
            "source": "Natural Earth 1:50m physical vectors, land (public domain)",
            "source_url": source_url,
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "clip_box": {"west": box[0], "south": box[1], "east": box[2], "north": box[3]},
            "decimals": decimals,
            "polygons": len(polygons),
            "points": sum(len(ring) for polygon in polygons for ring in polygon),
            "generator": "scripts/build_basemap.py",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": polygon},
            }
            for polygon in polygons
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--box", nargs=4, type=float, default=list(DEFAULT_BOX))
    arguments = parser.parse_args(argv)
    document = build(arguments.source, arguments.source_url, tuple(arguments.box))
    arguments.output.write_text(json.dumps(document, separators=(",", ":")) + "\n")
    print(json.dumps(document["properties"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
