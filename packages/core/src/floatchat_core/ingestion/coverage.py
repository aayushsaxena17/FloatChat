"""Exact interval/rectangle coverage from committed receipts, never object names."""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .numeric import Rejection
from .objects import CatalogueRecord, CatalogueSnapshot
from .planning import GEOMETRY_VERSION, Interval, Tile, month_start, shift_months


@dataclass(frozen=True)
class Receipt:
    identifier: uuid.UUID
    interval: Interval
    tile: Tile
    logical_key: str
    slot_version: int
    fetch_disposition: str
    stored_disposition: str
    committed_at: str


def covers(
    interval: Interval, tile: Tile, receipts: tuple[Receipt, ...], *, deadline: float
) -> bool:
    """Prove each integral-degree cell's continuous time, including split children."""
    if len(receipts) > 16384:
        raise Rejection("selector_receipt_limit")
    cells: dict[tuple[int, int], list[Interval]] = {
        (west, south): []
        for west in range(tile.west, tile.west + tile.width)
        for south in range(tile.south, tile.south + tile.height)
    }
    for receipt in receipts:
        if time.monotonic() >= deadline:
            raise Rejection("selector_coverage_deadline")
        if receipt.interval.end <= interval.start or receipt.interval.start >= interval.end:
            continue
        piece = Interval(
            max(interval.start, receipt.interval.start), min(interval.end, receipt.interval.end)
        )
        for west in range(
            max(tile.west, receipt.tile.west),
            min(tile.west + tile.width, receipt.tile.west + receipt.tile.width),
        ):
            for south in range(
                max(tile.south, receipt.tile.south),
                min(tile.south + tile.height, receipt.tile.south + receipt.tile.height),
            ):
                cells[(west, south)].append(piece)
    for pieces in cells.values():
        if time.monotonic() >= deadline:
            raise Rejection("selector_coverage_deadline")
        cursor = interval.start
        for piece in sorted(pieces, key=lambda value: (value.start, value.end)):
            if piece.start > cursor:
                return False
            cursor = max(cursor, piece.end)
            if cursor >= interval.end:
                break
        if cursor < interval.end:
            return False
    return True


def resolve(
    interval: Interval,
    records: tuple[CatalogueRecord, ...],
    versions: dict[str, int],
    receipts: tuple[Receipt, ...],
    members: Callable[[Interval, str], int],
    *,
    tiles: tuple[Tile, ...] | None = None,
    deadline: float,
) -> CatalogueSnapshot:
    if len(receipts) > 16384:
        raise Rejection("selector_receipt_limit")
    if tiles is None:
        tiles = tuple(
            Tile(west, south) for west in range(20, 120, 10) for south in range(-60, 30, 10)
        )
    if (
        not tiles
        or len(set(tiles)) != len(tiles)
        or len(tiles) > 90
        or any(
            tile.width != 10 or tile.height != 10 or (tile.west - 20) % 10 or (tile.south + 60) % 10
            for tile in tiles
        )
    ):
        raise Rejection("invalid_selector_tiles")
    # stage1-v4: a slot may have several active parts and one snapshot; a repeated partition
    # id or a second snapshot in one slot is still a corrupt catalogue.
    active: dict[str, list[CatalogueRecord]] = {}
    if len({record.partition_id for record in records}) != len(records):
        raise Rejection("duplicate_active_catalogue_slot")
    for record in records:
        group = active.setdefault(record.logical_key, [])
        if record.kind == "snapshot" and any(other.kind == "snapshot" for other in group):
            raise Rejection("duplicate_active_catalogue_slot")
        group.append(record)
    selected: list[CatalogueRecord] = []
    gaps = []
    empties: list[str] = []
    absences: list[str] = []
    month = month_start(interval.start)
    while month < interval.end:
        if time.monotonic() >= deadline:
            raise Rejection("selector_coverage_deadline")
        piece = Interval(max(month, interval.start), min(shift_months(month, 1), interval.end))
        for tile in tiles:
            slot = (
                f"argovis/core/{month:%Y-%m}/{tile.west}:{tile.south}/{GEOMETRY_VERSION}/"
                "argovis-core-v1/scientific-json-v2"
            )
            relevant = tuple(receipt for receipt in receipts if receipt.logical_key == slot)
            if not covers(piece, tile, relevant, deadline=deadline):
                gaps.append(slot + ":fetch_coverage")
            current = tuple(
                receipt for receipt in relevant if receipt.slot_version == versions.get(slot)
            )
            if members(piece, slot):
                if slot not in active:
                    gaps.append(slot + ":missing_active_generation")
                else:
                    selected.extend(active[slot])
                absences.extend(
                    f"{receipt.identifier}@{receipt.committed_at}"
                    for receipt in current
                    if receipt.fetch_disposition == "source_absence_over_retained"
                )
            else:
                empty = tuple(
                    receipt
                    for receipt in current
                    if receipt.stored_disposition.startswith("empty_stored_")
                )
                domains = tuple(
                    receipt
                    for receipt in empty
                    if receipt.stored_disposition == "empty_stored_domain"
                )
                if not domains and not covers(piece, tile, empty, deadline=deadline):
                    gaps.append(slot + ":stored_empty_not_verified")
                else:
                    empties.extend(
                        f"{receipt.identifier}@{receipt.committed_at}"
                        for receipt in (domains or empty)
                    )
        month = shift_months(month, 1)
    return CatalogueSnapshot(
        tuple(selected), versions, tuple(gaps), tuple(empties), tuple(absences)
    )
