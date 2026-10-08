"""Bounded immutable byte publication; store implementations have no retry authority.

This protocol is independent of PostgreSQL activation. A verified final object
remains unselectable until the scientific/catalogue transaction commits.
"""

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .numeric import Rejection

MAX_OBJECT_BYTES = 256 * 1024 * 1024
KEY = re.compile(
    r"(?:tmp/[0-9a-f]{32}/[0-9a-f]{32}|"
    r"raw/sha256/[0-9a-f]{64}\.json|normalised/sha256/[0-9a-f]{64}\.parquet)\Z"
)


def validate_key(key: str) -> None:
    if not KEY.fullmatch(key):
        raise Rejection("invalid_object_key")


class ObjectStore(Protocol):
    """Implementations must stop operation/cleanup by the absolute monotonic deadline.

    publish_if_absent uses destination conditional creation, never an
    unconditional CopyObject overwrite. All calls use a fixed configured bucket.
    """

    def write_temporary(self, key: str, data: bytes, deadline: float) -> None: ...

    def read(self, key: str, max_bytes: int, deadline: float) -> bytes: ...

    def publish_if_absent(self, temporary: str, final: str, deadline: float) -> None: ...


@dataclass(frozen=True)
class ObjectEvidence:
    key: str
    sha256: str
    byte_count: int
    temporary_key: str
    validation: dict[str, int | str]


def publish_verified(
    store: ObjectStore,
    payload: bytes,
    publication_id: uuid.UUID,
    validate: Callable[[bytes], dict[str, int | str]],
    *,
    deadline: float,
    raw: bool = False,
    max_bytes: int = MAX_OBJECT_BYTES,
    temporary_key: str | None = None,
) -> ObjectEvidence:
    if not 0 < max_bytes <= MAX_OBJECT_BYTES or len(payload) > max_bytes:
        raise Rejection("object_size_limit")
    digest = hashlib.sha256(payload).hexdigest()
    temporary = temporary_key or f"tmp/{publication_id.hex}/{uuid.uuid4().hex}"
    if not temporary.startswith(f"tmp/{publication_id.hex}/"):
        raise Rejection("invalid_temporary_key")
    final = f"raw/sha256/{digest}.json" if raw else f"normalised/sha256/{digest}.parquet"
    validate_key(temporary)
    validate_key(final)
    metadata = validate(payload)

    def remaining() -> float:
        if time.monotonic() >= deadline:
            raise Rejection("object_deadline")
        return min(deadline, time.monotonic() + 120)

    def verify(key: str) -> None:
        received = store.read(key, max_bytes, remaining())
        if len(received) != len(payload) or hashlib.sha256(received).hexdigest() != digest:
            raise Rejection("object_checksum_mismatch")
        if validate(received) != metadata:
            raise Rejection("object_validation_mismatch")

    store.write_temporary(temporary, payload, remaining())
    verify(temporary)
    store.publish_if_absent(temporary, final, remaining())
    verify(final)
    return ObjectEvidence(final, digest, len(payload), temporary, metadata)


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


@dataclass(frozen=True)
class CatalogueSnapshot:
    """One DB transaction resolves current membership, receipts and empty evidence."""

    records: tuple[CatalogueRecord, ...]
    current_slot_versions: dict[str, int]
    gaps: tuple[str, ...]
    empty_evidence: tuple[str, ...] = ()
    source_absence_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Selection:
    partitions: tuple[CatalogueRecord, ...]
    gaps: tuple[str, ...]
    empty_evidence: tuple[str, ...]
    source_absence_evidence: tuple[str, ...]


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
    slots: set[str] = set()
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
        if record.logical_key in slots:
            raise Rejection("duplicate_active_catalogue_slot")
        slots.add(record.logical_key)
        validate_key(record.key)
        if (
            record.byte_count < 0
            or record.byte_count > max_read_bytes - consumed
            or time.monotonic() >= deadline
        ):
            gaps.append(record.logical_key + ":verification_budget")
            continue
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
            gaps.append(record.logical_key + ":object_unavailable")
            continue
        selected.append(record)
    return Selection(
        tuple(selected), tuple(gaps), snapshot.empty_evidence, snapshot.source_absence_evidence
    )
