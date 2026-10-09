"""Non-destructive orphan proposals; no deletion operation exists in Stage 1."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .numeric import Rejection
from .objects import validate_key


@dataclass(frozen=True)
class ObjectInventory:
    key: str
    server_created_at: datetime | None
    reference_kinds: tuple[str, ...]
    publication_in_flight: bool
    active_lease: bool


@dataclass(frozen=True)
class OrphanProposal:
    key: str
    candidate: bool
    reasons: tuple[str, ...]
    checked_at: datetime
    server_created_at: datetime | None
    destructive: bool = False


def propose_orphan(item: ObjectInventory, now: datetime) -> OrphanProposal:
    validate_key(item.key)
    if now.tzinfo is None or (
        item.server_created_at is not None and item.server_created_at.tzinfo is None
    ):
        raise Rejection("orphan_clock_not_utc")
    reasons = []
    if item.server_created_at is None:
        reasons.append("unknown_server_creation_time")
    elif now - item.server_created_at < timedelta(hours=48):
        reasons.append("younger_than_minimum_age")
    if item.reference_kinds:
        reasons.append("persisted_reference")
    if item.publication_in_flight:
        reasons.append("publication_in_flight")
    if item.active_lease:
        reasons.append("active_lease")
    return OrphanProposal(item.key, not reasons, tuple(reasons), now, item.server_created_at)
