"""Candidate rows and level tables for slim staging; owner slots of profiles.

stage1-v4: a chunk stages one slim row per candidate (identity fields, hash, revision,
canonical text, level count) and its levels as typed columns for binary COPY. The
canonical content is no longer repeated as a float array inside the candidate, and no
retained population is previewed: SQL rechecks identities, revisions and manifests.
"""

import hashlib
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa

from .argovis import Profile
from .identity import StoredIdentity
from .numeric import CanonicalBudget, Rejection
from .parquet import PublicationSnapshotVerifier
from .planning import GEOMETRY_VERSION, Tile, month_start, timestamp
from .revisions import Revision

_PARAMETERS = ("pressure", "temperature", "salinity")
# Value columns of app.measurement_staging in table order (= app.core_measurement without
# profile_id, observation_month, level_index), with the PostgreSQL base type of each.
# Migration 0013 declares exactly these names; tests/stage1/test_spool.py checks the match.
MEASUREMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    *((p + s, "float8") for p in _PARAMETERS for s in ("", "_adjusted")),
    *((p + s, "float8") for p in _PARAMETERS for s in ("_error", "_original_error")),
    *((p + s, "text") for p in _PARAMETERS for s in ("_qc", "_adjusted_qc")),
    *((p + "_unit", "text") for p in _PARAMETERS),
    *((p + "_data_mode", "text") for p in _PARAMETERS),
    *((p + "_unit_source", "text") for p in _PARAMETERS),
    *((p + s, "text") for p in _PARAMETERS for s in ("_qc_source", "_adjusted_qc_source")),
    *((p + "_flags", "jsonb") for p in _PARAMETERS),
)
_ARROW = {
    "float8": pa.float64(),
    "text": pa.string(),
    "jsonb": pa.list_(pa.string()),
}
STAGING_SCHEMA = pa.schema(
    [
        pa.field("occurrence_index", pa.int32(), nullable=False),
        pa.field("level_index", pa.int32(), nullable=False),
        *(pa.field(name, _ARROW[kind]) for name, kind in MEASUREMENT_COLUMNS),
    ]
)


def slot_key(observed: datetime, longitude: Decimal, latitude: Decimal) -> str:
    """The `app.owner_slot` expression: UTC month x 10-degree tile of the exact position."""
    if not (20 <= longitude <= 120 and -60 <= latitude <= 30):
        raise Rejection("candidate_outside_region")
    west = 110 if longitude == 120 else int((longitude - 20) // 10) * 10 + 20
    south = 20 if latitude == 30 else int((latitude + 60) // 10) * 10 - 60
    tile = Tile(west, south)
    month = month_start(observed).strftime("%Y-%m")
    return (
        f"argovis/core/{month}/{tile.west}:{tile.south}/{GEOMETRY_VERSION}/"
        "argovis-core-v1/scientific-json-v2"
    )


def owner_slot(profile: Profile) -> str:
    return slot_key(
        timestamp(profile.observed_at),
        Decimal(profile.longitude.exact or "NaN"),
        Decimal(profile.latitude.exact or "NaN"),
    )


def staged_candidate(
    profile: Profile, proposed_id: uuid.UUID, raw_manifest_id: uuid.UUID
) -> dict[str, Any]:
    """Slim staging row: identity, hash, revision, canonical text and level count."""
    revision = (
        None
        if profile.revision is None
        else {
            "kind": profile.revision.kind,
            "components": {
                key: instant.isoformat() for key, instant in profile.revision.components
            },
        }
    )
    return {
        "proposed_profile_id": str(proposed_id),
        "source_profile_id": profile.source_profile_id,
        "platform": profile.platform,
        "cycle": profile.cycle,
        "direction": profile.direction,
        "observed_at": profile.observed_at,
        "identity_observed_at": profile.observed_at,
        "canonical": profile.canonical_bytes.decode(),
        "content_hash": profile.content_hash,
        "revision": revision,
        "raw_manifest_id": str(raw_manifest_id),
        "level_count": len(profile.levels),
    }


def staging_table(profile: Profile, occurrence_index: int) -> pa.Table:
    """The typed level rows of one candidate, columns exactly STAGING_SCHEMA."""
    levels = profile.levels
    columns = [
        pa.array([occurrence_index] * len(levels), pa.int32()),
        pa.array([level["level_index"] for level in levels], pa.int32()),
        *(
            pa.array([level[name] for level in levels], _ARROW[kind])
            for name, kind in MEASUREMENT_COLUMNS
        ),
    ]
    return pa.Table.from_arrays(columns, schema=STAGING_SCHEMA)


@dataclass(frozen=True)
class StoredScience:
    identity: StoredIdentity
    profile: Profile


@dataclass(frozen=True)
class StoredState:
    """What a revision comparison and a slot count need about a stored profile.

    No levels and no canonical bytes: the hash, the source revision and the position
    that decides the owner slot. Loaded in one batched query per chunk.
    """

    content_hash: str
    revision: Revision | None
    observed_at: datetime
    longitude: Decimal | None
    latitude: Decimal | None

    @property
    def slot(self) -> str:
        if self.longitude is None or self.latitude is None:
            raise Rejection("candidate_outside_region")
        return slot_key(self.observed_at, self.longitude, self.latitude)


def evidence_json(verified: dict[str, Any]) -> dict[str, Any]:
    """The writer's evidence without its in-process certificate object."""
    return {key: value for key, value in verified.items() if key != "certificate"}


def snapshot_certificate(
    verified: dict[str, Any],
    payload: bytes,
    *,
    deadline: float,
    budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]] | None = None,
) -> PublicationSnapshotVerifier:
    """The certificate write_snapshot issued for these exact bytes, else a fresh one that
    verifies the first payload fully (the pre-v4 writer returned no certificate)."""
    issued = verified.get("certificate")
    if isinstance(issued, PublicationSnapshotVerifier):
        return issued
    return PublicationSnapshotVerifier(
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        verified,
        deadline=deadline,
        budget_factory=budget_factory or (lambda: nullcontext(CanonicalBudget())),
    )
