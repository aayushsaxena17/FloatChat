"""Catalogue access on the read-only query login (ADR-0058): environment, tiles, coverage.

Coverage is proven by committed receipts through the Stage 1 resolver, never by object names.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import Engine, and_, create_engine, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from ..ingestion.coverage import Receipt, resolve
from ..ingestion.numeric import Rejection
from ..ingestion.objects import CatalogueRecord, CatalogueSnapshot
from ..ingestion.parquet import SCHEMA_VERSION
from ..ingestion.planning import (
    GEOMETRY_VERSION,
    MAPPINGS,
    Interval,
    Tile,
    month_start,
    shift_months,
)
from . import compile_sql
from .errors import QueryError
from .geography import ResolvedGeography, envelope_tiles
from .limits import QueryLimits

SOURCE = compile_sql.SOURCE


def slot_key(month: datetime, tile: Tile, source: str = SOURCE) -> str:
    return (
        f"{source}/core/{month:%Y-%m}/{tile.west}:{tile.south}/{GEOMETRY_VERSION}/"
        f"{MAPPINGS[source]}/scientific-json-v2"
    )


def months_of(interval: Interval) -> list[datetime]:
    months = []
    month = month_start(interval.start)
    while month < interval.end:
        months.append(month)
        month = shift_months(month, 1)
    return months


@dataclass(frozen=True)
class EnvironmentInfo:
    id: uuid.UUID
    name: str
    mode: str
    reference_time: datetime | None
    completed_runs: int

    @property
    def hot(self) -> Interval | None:
        if self.reference_time is None:
            return None
        return Interval(shift_months(self.reference_time, -3), self.reference_time)

    @property
    def window(self) -> Interval | None:
        if self.reference_time is None:
            return None
        return Interval(shift_months(self.reference_time, -12), self.reference_time)

    def describe(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "mode": self.mode,
            "reference_time": _iso(self.reference_time),
            "completed_runs": self.completed_runs,
            "hot_tier": _interval(self.hot),
            "postgresql_window": _interval(self.window),
        }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _interval(value: Interval | None) -> dict[str, str | None] | None:
    if value is None:
        return None
    return {"start": _iso(value.start), "end": _iso(value.end)}


@dataclass(frozen=True)
class SlotCoverage:
    logical_key: str
    month: str
    tile: Tile
    state: str  # covered | empty_verified | missing
    gaps: tuple[str, ...]
    profiles: int
    levels: int
    parts: tuple[CatalogueRecord, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "slot": self.logical_key,
            "month": self.month,
            "tile": {"west": self.tile.west, "south": self.tile.south},
            "state": self.state,
            "gaps": list(self.gaps),
            "profiles": self.profiles,
            "levels": self.levels,
            "parts": len(self.parts),
        }


@dataclass(frozen=True)
class Coverage:
    interval: Interval
    tiles: tuple[Tile, ...]
    slots: tuple[SlotCoverage, ...]
    manifests: dict[str, list[Any]] = field(default_factory=dict)

    @property
    def covered(self) -> tuple[SlotCoverage, ...]:
        return tuple(slot for slot in self.slots if slot.state == "covered")

    @property
    def missing(self) -> tuple[SlotCoverage, ...]:
        return tuple(slot for slot in self.slots if slot.state == "missing")

    @property
    def partial(self) -> bool:
        return bool(self.missing)

    @property
    def estimated_profiles(self) -> int:
        return sum(slot.profiles for slot in self.covered)

    @property
    def estimated_levels(self) -> int:
        return sum(slot.levels for slot in self.covered)

    @property
    def object_bytes(self) -> int:
        return sum(part.byte_count for slot in self.covered for part in slot.parts)

    def describe(self) -> dict[str, Any]:
        months = sorted({slot.month for slot in self.slots})
        return {
            "requested": _interval(self.interval),
            "months": months,
            "tiles": [{"west": t.west, "south": t.south} for t in self.tiles],
            "slots_total": len(self.slots),
            "slots_covered": len(self.covered),
            "slots_empty_verified": len([s for s in self.slots if s.state == "empty_verified"]),
            "slots_missing": len(self.missing),
            "missing": [slot.describe() for slot in self.missing],
            "estimated_profiles": self.estimated_profiles,
            "estimated_levels": self.estimated_levels,
            "partial": self.partial,
        }


def engine_from_url(url: str, limits: QueryLimits) -> Engine:
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres", "postgresql+psycopg"):
        raise ValueError("postgresql URL required")
    normalized = urlunsplit(("postgresql+psycopg", parts.netloc, parts.path, parts.query, ""))
    milliseconds = int(limits.query_timeout_seconds * 1000)
    return create_engine(
        normalized,
        pool_size=4,
        max_overflow=4,
        pool_pre_ping=True,
        pool_recycle=600,
        connect_args={
            "connect_timeout": 3,
            "options": f"-c statement_timeout={milliseconds} -c default_transaction_read_only=on",
        },
    )


def translate_error(error: Exception) -> QueryError:
    """Database failures become registered codes; no SQL or driver text reaches a client."""
    if isinstance(error, DBAPIError):
        original = getattr(error, "orig", None)
        sqlstate = getattr(original, "sqlstate", None)
        if sqlstate == "57014":
            return QueryError("statement_timeout")
    if isinstance(error, (OperationalError, SQLAlchemyError)):
        return QueryError("execution_failed")
    return QueryError("internal_error")


class QueryCatalogue:
    def __init__(self, engine: Engine, limits: QueryLimits | None = None) -> None:
        self.engine = engine
        self.limits = limits or QueryLimits()

    def environment(self) -> EnvironmentInfo:
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(compile_sql.environment_statement()).mappings().all()
        except SQLAlchemyError as error:
            raise translate_error(error) from None
        if len(rows) != 1:
            raise QueryError("coverage_missing", message="No ingestion environment is configured.")
        row = rows[0]
        return EnvironmentInfo(
            row["id"], row["name"], row["mode"], row["reference_time"], int(row["completed_runs"])
        )

    def tiles_for(self, geography: ResolvedGeography) -> tuple[Tile, ...]:
        candidates = envelope_tiles(geography.boxes)
        if geography.kind != "named_region" or not candidates:
            return candidates
        assert geography.region is not None
        statement = compile_sql.region_tiles_statement(
            geography.region.name,
            geography.region.version,
            [(tile.west, tile.south) for tile in candidates],
        )
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(statement).all()
        except SQLAlchemyError as error:
            raise translate_error(error) from None
        return tuple(sorted(Tile(int(west), int(south)) for west, south in rows))

    def coverage(
        self, environment_id: uuid.UUID, interval: Interval, tiles: tuple[Tile, ...]
    ) -> Coverage:
        months = months_of(interval)
        if not tiles or not months:
            return Coverage(interval, tiles, ())
        keys = [slot_key(month, tile) for month in months for tile in tiles]
        first_month = months[0].date()
        last_month = months[-1].date()
        try:
            with self.engine.connect() as connection:
                slots = (
                    connection.execute(
                        select(
                            compile_sql.slot.c.logical_key,
                            compile_sql.slot.c.slot_version,
                            compile_sql.slot.c.membership_manifest,
                        ).where(
                            compile_sql.slot.c.environment_id == environment_id,
                            compile_sql.slot.c.logical_key.in_(keys),
                        )
                    )
                    .mappings()
                    .all()
                )
                parts = (
                    connection.execute(
                        select(compile_sql.partition)
                        .where(
                            compile_sql.partition.c.environment_id == environment_id,
                            compile_sql.partition.c.logical_key.in_(keys),
                        )
                        .order_by(
                            compile_sql.partition.c.logical_key, compile_sql.partition.c.generation
                        )
                    )
                    .mappings()
                    .all()
                )
                receipts = (
                    connection.execute(
                        select(compile_sql.receipt)
                        .where(
                            compile_sql.receipt.c.environment_id == environment_id,
                            compile_sql.receipt.c.logical_key.in_(keys),
                            or_(
                                and_(
                                    compile_sql.receipt.c.requested_start < interval.end,
                                    compile_sql.receipt.c.requested_end > interval.start,
                                ),
                                and_(
                                    compile_sql.receipt.c.stored_disposition
                                    == "empty_stored_domain",
                                    compile_sql.receipt.c.observation_month.between(
                                        first_month, last_month
                                    ),
                                ),
                            ),
                        )
                        .order_by(compile_sql.receipt.c.committed_at, compile_sql.receipt.c.id)
                        .limit(16385)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise translate_error(error) from None
        versions = {row["logical_key"]: int(row["slot_version"]) for row in slots}
        manifests = {row["logical_key"]: list(row["membership_manifest"] or []) for row in slots}
        records = tuple(
            CatalogueRecord(
                row["id"],
                row["environment_id"],
                row["logical_key"],
                int(row["generation"]),
                int(row["slot_version"]),
                "active",
                True,
                True,
                row["geometry_version"],
                SCHEMA_VERSION,
                row["object_key"],
                row["sha256"],
                int(row["bytes"]),
                row["kind"],
                row["part_ordinal"],
            )
            for row in parts
        )
        receipt_records = tuple(
            Receipt(
                row["id"],
                Interval(row["requested_start"], row["requested_end"]),
                Tile(**row["tile"]),
                row["logical_key"],
                int(row["slot_version"]),
                row["fetch_disposition"],
                row["stored_disposition"],
                row["committed_at"].isoformat(),
            )
            for row in receipts
        )

        def members(piece: Interval, slot: str) -> int:
            return len(manifests.get(slot, []))

        try:
            snapshot: CatalogueSnapshot = resolve(
                interval,
                records,
                versions,
                receipt_records,
                members,
                tiles=tiles,
                deadline=time.monotonic() + self.limits.query_timeout_seconds,
            )
        except Rejection as error:
            raise QueryError("execution_failed", message=f"Catalogue rejected: {error}") from None
        gaps_by_slot: dict[str, list[str]] = {}
        for gap in snapshot.gaps:
            slot, _, reason = gap.rpartition(":")
            gaps_by_slot.setdefault(slot, []).append(reason)
        selected: dict[str, list[CatalogueRecord]] = {}
        for record in snapshot.records:
            selected.setdefault(record.logical_key, []).append(record)
        results = []
        for month in months:
            for tile in tiles:
                key = slot_key(month, tile)
                manifest = manifests.get(key, [])
                gaps = tuple(gaps_by_slot.get(key, ()))
                if gaps:
                    state = "missing"
                elif manifest:
                    state = "covered"
                else:
                    state = "empty_verified"
                results.append(
                    SlotCoverage(
                        key,
                        f"{month:%Y-%m}",
                        tile,
                        state,
                        gaps,
                        len(manifest),
                        sum(int(entry.get("levels", 0)) for entry in manifest),
                        tuple(selected.get(key, ())),
                    )
                )
        return Coverage(interval, tiles, tuple(results), manifests)


def clip_to_months(start: datetime, end: datetime) -> Interval:
    """The request interval as the resolver expects it (UTC, start < end)."""
    if end <= start:
        end = start + timedelta(microseconds=1)
    return Interval(start, end)
