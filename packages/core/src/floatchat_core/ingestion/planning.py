"""Immutable UTC eligibility and indian-ocean-v1 ownership/planning."""

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from .numeric import Rejection

GEOMETRY_VERSION = "indian-ocean-v1"
# Mapping version (and logical-key namespace) of each source population.
MAPPINGS = {"argovis": "argovis-core-v1", "gdac": "gdac-core-v1"}
WKT = "POLYGON((20 -60,120 -60,120 30,20 30,20 -60))"
GEOMETRY_SHA256 = hashlib.sha256(WKT.encode()).hexdigest()
ACCEPTANCE_REFERENCE = datetime(2025, 4, 1, tzinfo=UTC)
PLAN_VERSION = "indian-ocean-plan-v2"
# stage1-v3 run-level policy, persisted with each admitted run's limits (ADR-0040/0041).
RUN_POLICY = {
    "contract": "stage1-v3",
    "plan_version": PLAN_VERSION,
    "source_policy": "S1-SOURCE-2",
    "canonical_run_bytes": 40 * 1024**3,
}


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise Rejection("invalid_timestamp")
    # Reject precision truncation and timezone-naive source timestamps.
    if re.search(r"\.\d{7,}", value):
        raise Rejection("timestamp_precision")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Rejection("invalid_timestamp") from None
    if parsed.tzinfo is None:
        raise Rejection("timezone_required")
    return parsed.astimezone(UTC)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise Rejection("timezone_required")
    return value.astimezone(UTC)


def month_start(value: datetime) -> datetime:
    return utc(value).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def shift_months(value: datetime, delta: int) -> datetime:
    value = utc(value)
    count = value.year * 12 + value.month - 1 + delta
    year, month = divmod(count, 12)
    return value.replace(
        year=year, month=month + 1, day=min(value.day, calendar.monthrange(year, month + 1)[1])
    )


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if utc(self.start) != self.start or utc(self.end) != self.end or self.start >= self.end:
            raise Rejection("invalid_interval")

    def contains(self, instant: datetime) -> bool:
        return self.start <= utc(instant) < self.end


def month_interval(first: str, last: str) -> Interval:
    if not all(re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", x) for x in (first, last)):
        raise Rejection("invalid_month")
    try:
        start = datetime.strptime(first, "%Y-%m").replace(tzinfo=UTC)
        end = shift_months(datetime.strptime(last, "%Y-%m").replace(tzinfo=UTC), 1)
        return Interval(start, end)
    except ValueError:
        raise Rejection("invalid_month_interval") from None


@dataclass(frozen=True)
class RunPolicy:
    reference: datetime
    mode: Literal["normal", "acceptance"]
    environment_id: str

    @classmethod
    def capture(
        cls,
        mode: Literal["normal", "acceptance"],
        environment_id: str,
        *,
        acceptance_marker: bool = False,
        actual_now: datetime | None = None,
    ) -> "RunPolicy":
        if mode == "acceptance":
            if not acceptance_marker:
                raise Rejection("acceptance_environment_required")
            return cls(ACCEPTANCE_REFERENCE, mode, environment_id)
        if mode != "normal":
            raise Rejection("invalid_mode")
        return cls(utc(actual_now or datetime.now(UTC)), mode, environment_id)

    @property
    def eligible(self) -> Interval:
        return Interval(shift_months(self.reference, -12), self.reference)

    @property
    def hot(self) -> Interval:
        return Interval(shift_months(self.reference, -3), self.reference)

    def validate(self, interval: Interval) -> None:
        if interval.start < self.eligible.start or interval.end > self.reference:
            raise Rejection("outside_rolling_window")


@dataclass(frozen=True, order=True)
class Tile:
    west: int
    south: int
    width: int = 10
    height: int = 10

    def __post_init__(self) -> None:
        if not (
            20 <= self.west < 120
            and -60 <= self.south < 30
            and 1 <= self.width <= 10
            and 1 <= self.height <= 10
            and self.west + self.width <= 120
            and self.south + self.height <= 30
        ):
            raise Rejection("invalid_tile")

    @property
    def key(self) -> str:
        return f"{self.west}:{self.south}:{self.width}:{self.height}"

    def owns(self, longitude: Decimal, latitude: Decimal) -> bool:
        east, north = self.west + self.width, self.south + self.height
        return (
            self.west <= longitude
            and (longitude < east or longitude == east == 120)
            and self.south <= latitude
            and (latitude < north or latitude == north == 30)
        )

    def polygon(self) -> str:
        epsilon = Decimal("0.000001")
        w, s = Decimal(self.west) - epsilon, Decimal(self.south) - epsilon
        e, n = (
            Decimal(self.west + self.width) + epsilon,
            Decimal(self.south + self.height) + epsilon,
        )
        return json.dumps(
            [
                [float(w), float(s)],
                [float(e), float(s)],
                [float(e), float(n)],
                [float(w), float(n)],
                [float(w), float(s)],
            ],
            separators=(",", ":"),
        )


def in_region(longitude: Decimal, latitude: Decimal) -> bool:
    if not isinstance(longitude, Decimal) or not isinstance(latitude, Decimal):
        raise Rejection("invalid_coordinates")
    if not (
        longitude.is_finite()
        and latitude.is_finite()
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        raise Rejection("invalid_coordinates")
    return 20 <= longitude <= 120 and -60 <= latitude <= 30


@dataclass(frozen=True)
class PlannedChunk:
    interval: Interval
    tile: Tile


def plan(interval: Interval, *, max_chunks: int = 16384) -> tuple[PlannedChunk, ...]:
    if not 0 < max_chunks <= 16384:
        raise Rejection("invalid_chunk_limit")
    result: list[PlannedChunk] = []
    cursor = interval.start
    while cursor < interval.end:
        # Plan v2 (ADR-0041): one initial slice per UTC calendar month, so each
        # month/tile slot publishes once per run unless adaptive splitting is needed.
        end = min(shift_months(month_start(cursor), 1), interval.end)
        for west in range(20, 120, 10):
            for south in range(-60, 30, 10):
                if len(result) >= max_chunks:
                    raise Rejection("chunk_count_limit")
                result.append(PlannedChunk(Interval(cursor, end), Tile(west, south)))
        cursor = end
    return tuple(result)


def split(chunk: PlannedChunk) -> tuple[PlannedChunk, ...]:
    duration = chunk.interval.end - chunk.interval.start
    if duration >= timedelta(hours=2):
        middle = chunk.interval.start + duration / 2
        return (
            PlannedChunk(Interval(chunk.interval.start, middle), chunk.tile),
            PlannedChunk(Interval(middle, chunk.interval.end), chunk.tile),
        )
    tile = chunk.tile
    if tile.width >= 2:
        width = tile.width // 2
        return (
            PlannedChunk(chunk.interval, Tile(tile.west, tile.south, width, tile.height)),
            PlannedChunk(
                chunk.interval, Tile(tile.west + width, tile.south, tile.width - width, tile.height)
            ),
        )
    if tile.height >= 2:
        height = tile.height // 2
        return (
            PlannedChunk(chunk.interval, Tile(tile.west, tile.south, tile.width, height)),
            PlannedChunk(
                chunk.interval,
                Tile(tile.west, tile.south + height, tile.width, tile.height - height),
            ),
        )
    raise Rejection("minimum_chunk_exceeded")
