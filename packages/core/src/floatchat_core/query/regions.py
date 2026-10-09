"""Committed named-region fixture (ADR-0060): names, versions, citations and WKT digests."""

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).with_name("regions") / "named_regions.json"
FIXTURE_SCHEMA = "named-regions-fixture-v1"


@dataclass(frozen=True)
class RegionRecord:
    name: str
    version: str
    kind: str
    source: str
    source_id: str | None
    citation: str
    simplify_tolerance_deg: float | None
    min_part_area_km2: float | None
    clipped: bool
    bbox: tuple[float, float, float, float]
    vertices: int
    area_km2: float
    note: str
    wkt: str
    sha256: str

    def public(self) -> dict[str, Any]:
        """Catalogue entry without the geometry text (plan section 5.2)."""
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "source": self.source,
            "source_id": self.source_id,
            "citation": self.citation,
            "simplify_tolerance_deg": self.simplify_tolerance_deg,
            "min_part_area_km2": self.min_part_area_km2,
            "clipped": self.clipped,
            "bbox": {
                "west": self.bbox[0],
                "south": self.bbox[1],
                "east": self.bbox[2],
                "north": self.bbox[3],
            },
            "vertices": self.vertices,
            "area_km2": self.area_km2,
            "sha256": self.sha256,
            "note": self.note,
        }


@cache
def load_regions() -> tuple[RegionRecord, ...]:
    document = json.loads(FIXTURE.read_text())
    if document.get("schema") != FIXTURE_SCHEMA:
        raise ValueError("unsupported named-region fixture")
    records = []
    for row in document["regions"]:
        digest = hashlib.sha256(row["wkt"].encode()).hexdigest()
        if digest != row["sha256"]:
            raise ValueError("named-region digest mismatch")
        bbox = row["bbox"]
        records.append(
            RegionRecord(
                row["name"],
                row["version"],
                row["kind"],
                row["source"],
                row.get("source_id"),
                row["citation"],
                row.get("simplify_tolerance_deg"),
                row.get("min_part_area_km2"),
                bool(row["clipped"]),
                (bbox["west"], bbox["south"], bbox["east"], bbox["north"]),
                int(row["vertices"]),
                float(row["area_km2"]),
                row.get("note", ""),
                row["wkt"],
                row["sha256"],
            )
        )
    names = [record.name for record in records]
    if len(set(names)) != len(names):
        raise ValueError("duplicate named region")
    return tuple(records)


def find_region(name: str) -> RegionRecord | None:
    for record in load_regions():
        if record.name == name:
            return record
    return None
