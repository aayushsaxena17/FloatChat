"""Stage 1 internal catalogue proof; no public query endpoint or query engine."""

import time
import uuid

from .numeric import Rejection
from .objects import ObjectStore, Selection
from .objects import select_active_partitions as verify_objects
from .parquet import SCHEMA_VERSION
from .planning import GEOMETRY_VERSION, MAPPINGS, Interval, Tile
from .repository import Repository


def select_active_partitions(
    repository: Repository,
    store: ObjectStore,
    environment: uuid.UUID,
    interval: Interval,
    geometry_version: str,
    schema_version: str,
    *,
    tiles: tuple[Tile, ...] | None = None,
    max_seconds: float = 600,
    max_read_bytes: int = 10 * 1024**3,
    source: str = "argovis",
) -> Selection:
    if (
        geometry_version != GEOMETRY_VERSION
        or schema_version != SCHEMA_VERSION
        or source not in MAPPINGS
    ):
        raise Rejection("unsupported_catalogue_version")
    if not (0 < max_seconds <= 600 and 0 < max_read_bytes <= 10 * 1024**3):
        raise Rejection("invalid_selector_budget")
    deadline = time.monotonic() + max_seconds
    try:
        snapshot = repository.catalogue_snapshot(
            environment, interval, tiles=tiles, max_seconds=min(60, max_seconds), source=source
        )
    except Rejection as error:
        return Selection((), ("catalogue_unavailable:" + error.category,), (), ())
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return Selection((), ("catalogue_verification_budget",), (), ())
    return verify_objects(
        snapshot,
        store,
        environment,
        geometry_version,
        schema_version,
        max_seconds=remaining,
        max_read_bytes=max_read_bytes,
    )
