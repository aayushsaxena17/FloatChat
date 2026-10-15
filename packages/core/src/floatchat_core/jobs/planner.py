"""From a request to chunks (ADR-0078, ADR-0079).

The required slots are the request's months times the tiles its geography touches. A slot the
catalogue already covers (committed science or a verified empty fetch) is reused; the missing
slots are grouped into fetch chunks, one per contiguous run of months inside a calendar year,
so each chunk is one historical ingestion run of at most twelve months whose reference time is
its end. The export chunk always comes last.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..ingestion.planning import Interval, Tile, month_start, shift_months
from ..query.catalogue import Coverage, months_of


@dataclass(frozen=True)
class ChunkSpec:
    kind: str
    label: str
    interval_start: datetime | None
    interval_end: datetime | None
    tiles: list[list[int]]
    state: str = "pending"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchPlan:
    slots_total: int
    slots_reused: int
    slots_missing: int
    chunks: tuple[ChunkSpec, ...]
    missing_months: tuple[str, ...]

    @property
    def reuse_ratio(self) -> float:
        return 1.0 if self.slots_total == 0 else self.slots_reused / self.slots_total

    def describe(self) -> dict[str, Any]:
        return {
            "slots_total": self.slots_total,
            "slots_reused": self.slots_reused,
            "slots_missing": self.slots_missing,
            "reuse_ratio": round(self.reuse_ratio, 4),
            "fetch_chunks": sum(1 for chunk in self.chunks if chunk.kind == "fetch"),
            "missing_months": list(self.missing_months),
        }


def _month_key(month: datetime) -> str:
    return f"{month:%Y-%m}"


def plan_chunks(
    interval: Interval, tiles: tuple[Tile, ...], coverage: Coverage, *, now: datetime | None = None
) -> FetchPlan:
    """Fetch chunks for the months with missing slots, then one export chunk.

    Months are fetched whole (Stage 1 plans whole calendar months); the export filters the
    exact interval. A month that has not ended yet cannot be fetched historically and is left
    missing: the export reports it in the coverage list.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    months = months_of(interval)
    states = {slot.logical_key: slot.state for slot in coverage.slots}
    missing_by_month: dict[datetime, set[Tile]] = {}
    total = reused = 0
    from ..query.catalogue import slot_key

    for month in months:
        for tile in tiles:
            total += 1
            state = states.get(slot_key(month, tile), "missing")
            if state == "missing":
                missing_by_month.setdefault(month, set()).add(tile)
            else:
                reused += 1
    fetchable = [month for month in sorted(missing_by_month) if shift_months(month, 1) <= moment]
    chunks: list[ChunkSpec] = []
    group: list[datetime] = []

    def flush() -> None:
        if not group:
            return
        start, end = group[0], shift_months(group[-1], 1)
        cells = sorted({tile for month in group for tile in missing_by_month[month]})
        label = (
            _month_key(start)
            if len(group) == 1
            else f"{_month_key(start)}..{_month_key(group[-1])}"
        )
        chunks.append(
            ChunkSpec(
                "fetch",
                label,
                start,
                end,
                [[tile.west, tile.south] for tile in cells],
                evidence={"months": [_month_key(m) for m in group]},
            )
        )
        group.clear()

    for month in fetchable:
        if group and (month.year != group[-1].year or shift_months(group[-1], 1) != month):
            flush()
        group.append(month)
    flush()
    chunks.append(
        ChunkSpec(
            "export", "export", interval.start, interval.end, [[t.west, t.south] for t in tiles]
        )
    )
    return FetchPlan(
        slots_total=total,
        slots_reused=reused,
        slots_missing=total - reused,
        chunks=tuple(chunks),
        missing_months=tuple(_month_key(month) for month in sorted(missing_by_month)),
    )


def month_of(value: datetime) -> datetime:
    return month_start(value)
