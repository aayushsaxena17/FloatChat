"""Geography resolution and the Stage 1 tiles a request touches (contract section 3.1)."""

import math
from dataclasses import dataclass
from typing import Literal

from ..ingestion.planning import GEOMETRY_VERSION, WKT, Tile
from .errors import QueryError
from .plan import BoundingBox, NamedRegion, PointRadius
from .regions import RegionRecord, find_region

ENVELOPE_WKT = WKT
ENVELOPE_VERSION = GEOMETRY_VERSION
ENVELOPE = (20.0, -60.0, 120.0, 30.0)
TILE_DEGREES = 10
EARTH_RADIUS_M = 6_371_008.8
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class ResolvedGeography:
    kind: Literal["named_region", "bbox", "point_radius"]
    label: str
    boxes: tuple[Box, ...]
    region: RegionRecord | None = None
    point: tuple[float, float] | None = None
    radius_m: float | None = None

    def describe(self) -> dict[str, object]:
        if self.kind == "named_region" and self.region is not None:
            return {
                "kind": "named_region",
                "name": self.region.name,
                "version": self.region.version,
                "sha256": self.region.sha256,
                "clipped": self.region.clipped,
            }
        if self.kind == "bbox":
            return {
                "kind": "bbox",
                "boxes": [
                    {"west": w, "south": s, "east": e, "north": n} for w, s, e, n in self.boxes
                ],
            }
        assert self.point is not None and self.radius_m is not None
        return {
            "kind": "point_radius",
            "longitude": self.point[0],
            "latitude": self.point[1],
            "radius_m": self.radius_m,
        }


def point_radius_boxes(longitude: float, latitude: float, radius_m: float) -> tuple[Box, ...]:
    """Bounding boxes of a geodesic circle, split at the antimeridian, clamped to the sphere."""
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    south, north = max(-90.0, latitude - dlat), min(90.0, latitude + dlat)
    if south <= -90.0 + 1e-9 or north >= 90.0 - 1e-9:
        return ((-180.0, south, 180.0, north),)
    widest = max(abs(south), abs(north))
    dlon = math.degrees(radius_m / (EARTH_RADIUS_M * math.cos(math.radians(widest))))
    if dlon >= 180.0:
        return ((-180.0, south, 180.0, north),)
    west, east = longitude - dlon, longitude + dlon
    if west < -180.0:
        return ((west + 360.0, south, 180.0, north), (-180.0, south, east, north))
    if east > 180.0:
        return ((west, south, 180.0, north), (-180.0, south, east - 360.0, north))
    return ((west, south, east, north),)


def resolve_geography(geography: NamedRegion | BoundingBox | PointRadius) -> ResolvedGeography:
    if isinstance(geography, NamedRegion):
        record = find_region(geography.value)
        if record is None:
            raise QueryError("unknown_region")
        return ResolvedGeography("named_region", record.name, (record.bbox,), region=record)
    if isinstance(geography, BoundingBox):
        return ResolvedGeography("bbox", "bbox", geography.envelopes())
    radius_m = geography.radius_km * 1000.0
    return ResolvedGeography(
        "point_radius",
        "point_radius",
        point_radius_boxes(geography.longitude, geography.latitude, radius_m),
        point=(geography.longitude, geography.latitude),
        radius_m=radius_m,
    )


def envelope_tiles(boxes: tuple[Box, ...]) -> tuple[Tile, ...]:
    """Stage 1 tiles whose [west, west+10) x [south, south+10) cell meets any box.

    The envelope's outer east and north edges belong to the last tile (contract section 3.1).
    """
    found: set[Tile] = set()
    west0, south0, east0, north0 = ENVELOPE
    for west, south, east, north in boxes:
        if east < west0 or west > east0 or north < south0 or south > north0:
            continue
        first_x = max(0, math.floor((max(west, west0) - west0) / TILE_DEGREES))
        last_x = min(9, math.floor((min(east, east0) - west0) / TILE_DEGREES))
        first_y = max(0, math.floor((max(south, south0) - south0) / TILE_DEGREES))
        last_y = min(8, math.floor((min(north, north0) - south0) / TILE_DEGREES))
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                found.add(Tile(int(west0) + x * TILE_DEGREES, int(south0) + y * TILE_DEGREES))
    return tuple(sorted(found))


def all_tiles() -> tuple[Tile, ...]:
    return tuple(Tile(west, south) for west in range(20, 120, 10) for south in range(-60, 30, 10))
