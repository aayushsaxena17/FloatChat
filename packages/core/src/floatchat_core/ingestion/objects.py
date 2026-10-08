"""Bounded immutable byte publication; store implementations have no retry authority.

This protocol is independent of PostgreSQL activation. A verified final object
remains unselectable until the scientific/catalogue transaction commits.
"""

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .numeric import Rejection

MAX_OBJECT_BYTES = 256 * 1024 * 1024
KEY = re.compile(
    r"(?:tmp/[0-9a-f]{32}/[0-9a-f]{32}|"
    r"raw/sha256/[0-9a-f]{64}\.(?:json|nc)|normalised/sha256/[0-9a-f]{64}\.parquet)\Z"
)


def validate_key(key: str) -> None:
    if not KEY.fullmatch(key):
        raise Rejection("invalid_object_key")


class ObjectStore(Protocol):
    """Implementations must stop operation/cleanup by the absolute monotonic deadline.

    write_immutable creates a final key only if it is absent (conditional create, never
    an overwrite) with a SHA-256 the store verifies against the stored bytes; a key that
    already exists is left alone and its content must equal sha256_hex, else
    object_checksum_mismatch. stat reports an object's byte count and its stored SHA-256
    (hex) when the store keeps one. write_temporary and publish_if_absent (destination
    conditional creation, never an unconditional CopyObject overwrite) remain for one
    release and are no longer used by publish_verified. All calls use a fixed configured
    bucket.
    """

    def write_temporary(self, key: str, data: bytes, deadline: float) -> None: ...

    def write_immutable(self, key: str, data: bytes, sha256_hex: str, deadline: float) -> None: ...

    def stat(self, key: str, deadline: float) -> dict[str, Any]: ...

    def read(self, key: str, max_bytes: int, deadline: float) -> bytes: ...

    def publish_if_absent(self, temporary: str, final: str, deadline: float) -> None: ...


@dataclass(frozen=True)
class ObjectEvidence:
    key: str
    sha256: str
    byte_count: int
    temporary_key: str | None  # reserved by the caller; no temporary object is written
    validation: dict[str, int | str]


def publish_verified(
    store: ObjectStore,
    payload: bytes,
    publication_id: uuid.UUID,
    validate: Callable[[bytes], dict[str, int | str]],
    *,
    deadline: float,
    raw: bool | str = False,
    max_bytes: int = MAX_OBJECT_BYTES,
    temporary_key: str | None = None,
    audit: bool = False,
) -> ObjectEvidence:
    """Validate once, create the content-addressed key with a server-verified SHA-256, stat it.

    raw=True addresses raw/sha256/<hex>.json; raw="nc" addresses a NetCDF raw object.
    audit=True additionally reads the stored object back and validates it again.
    """
    if not 0 < max_bytes <= MAX_OBJECT_BYTES or len(payload) > max_bytes:
        raise Rejection("object_size_limit")
    digest = hashlib.sha256(payload).hexdigest()
    if temporary_key is not None:
        if not temporary_key.startswith(f"tmp/{publication_id.hex}/"):
            raise Rejection("invalid_temporary_key")
        validate_key(temporary_key)
    extension = "json" if raw is True else raw
    final = f"raw/sha256/{digest}.{extension}" if raw else f"normalised/sha256/{digest}.parquet"
    validate_key(final)
    metadata = validate(payload)

    def remaining() -> float:
        if time.monotonic() >= deadline:
            raise Rejection("object_deadline")
        return min(deadline, time.monotonic() + 120)

    store.write_immutable(final, payload, digest, remaining())
    stored = store.stat(final, remaining())
    if stored.get("bytes") != len(payload) or stored.get("sha256") not in (None, digest):
        raise Rejection("object_checksum_mismatch")
    if audit:
        received = store.read(final, max_bytes, remaining())
        if len(received) != len(payload) or hashlib.sha256(received).hexdigest() != digest:
            raise Rejection("object_checksum_mismatch")
        if validate(received) != metadata:
            raise Rejection("object_validation_mismatch")
    return ObjectEvidence(final, digest, len(payload), temporary_key, metadata)


@dataclass(frozen=True)
class CatalogueRecord:
    partition_id: uuid.UUID
    environment_id: uuid.UUID
    logical_key: str
    generation: int
    slot_version: int
    status: str
    committed: bool
    verified: bool
    geometry_version: str
    schema_version: str
    key: str
    sha256: str
    byte_count: int
    kind: str = "snapshot"  # stage1-v4: "part" (own profiles of one chunk) or "snapshot"
    part_ordinal: int | None = None


@dataclass(frozen=True)
class CatalogueSnapshot:
    """One DB transaction resolves current membership, receipts and empty evidence."""

    records: tuple[CatalogueRecord, ...]
    current_slot_versions: dict[str, int]
    gaps: tuple[str, ...]
    empty_evidence: tuple[str, ...] = ()
    source_absence_evidence: tuple[str, ...] = ()
    # Slot membership manifests of the slots that have active records (stage1-v4).
    manifests: dict[str, list[Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Selection:
    """Every active part and snapshot of each selected slot, in generation order.

    Readers keep a row only if its (profile_id, profile_hash) is in manifests[slot]; a
    profile replaced or moved by a later part is excluded by the manifest, not by file.
    """

    partitions: tuple[CatalogueRecord, ...]
    gaps: tuple[str, ...]
    empty_evidence: tuple[str, ...]
    source_absence_evidence: tuple[str, ...]
    manifests: dict[str, list[Any]] = field(default_factory=dict)


def select_active_partitions(
    snapshot: CatalogueSnapshot,
    store: ObjectStore,
    environment: uuid.UUID,
    geometry_version: str,
    schema_version: str,
    *,
    max_seconds: float = 600,
    max_read_bytes: int = 10 * 1024**3,
) -> Selection:
    """Internal byte integrity proof over a persisted catalogue snapshot, no queries.

    Membership/coverage resolution is the database repository's responsibility;
    neither object names nor this verifier manufacture coverage receipts.
    """
    if not (0 < max_seconds <= 600 and 0 < max_read_bytes <= 10 * 1024**3):
        raise Rejection("invalid_selector_budget")
    deadline = time.monotonic() + max_seconds
    selected: list[CatalogueRecord] = []
    gaps = list(snapshot.gaps)
    consumed = 0
    by_slot: dict[str, list[CatalogueRecord]] = {}
    for record in snapshot.records:
        if (
            record.environment_id != environment
            or record.status != "active"
            or not record.committed
            or not record.verified
            or record.geometry_version != geometry_version
            or record.schema_version != schema_version
            or snapshot.current_slot_versions.get(record.logical_key) != record.slot_version
        ):
            continue
        members = by_slot.setdefault(record.logical_key, [])
        if any(other.partition_id == record.partition_id for other in members) or (
            record.kind == "snapshot" and any(other.kind == "snapshot" for other in members)
        ):
            raise Rejection("duplicate_active_catalogue_slot")
        members.append(record)
    selected_slots: list[str] = []
    for slot, records in by_slot.items():
        # A slot is answerable only with all of its active objects; one unreadable part
        # makes the whole slot a gap, never a partial substitute.
        failure = None
        for record in records:
            validate_key(record.key)
            if (
                record.byte_count < 0
                or record.byte_count > max_read_bytes - consumed
                or time.monotonic() >= deadline
            ):
                failure = "verification_budget"
                break
            consumed += record.byte_count  # Reserve before I/O, including unsuccessful reads.
            try:
                received = store.read(
                    record.key, record.byte_count, min(deadline, time.monotonic() + 120)
                )
                if (
                    len(received) != record.byte_count
                    or hashlib.sha256(received).hexdigest() != record.sha256
                ):
                    raise Rejection("object_checksum_mismatch")
            except (Rejection, OSError, TimeoutError):
                failure = "object_unavailable"
                break
        if failure is not None:
            gaps.append(slot + ":" + failure)
            continue
        selected.extend(records)
        selected_slots.append(slot)
    return Selection(
        tuple(selected),
        tuple(gaps),
        snapshot.empty_evidence,
        snapshot.source_absence_evidence,
        {slot: snapshot.manifests[slot] for slot in selected_slots if slot in snapshot.manifests},
    )
