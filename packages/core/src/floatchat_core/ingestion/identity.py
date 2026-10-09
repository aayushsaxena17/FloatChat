"""Conservative identity decisions; the DB enforces admission under context locks."""

import uuid
from dataclasses import dataclass

from .argovis import Profile
from .numeric import Rejection

NaturalKey = tuple[str, int, str, str, str]


@dataclass(frozen=True)
class StoredIdentity:
    id: uuid.UUID
    platform: str
    source_profile_id: str | None
    cycle: int | None
    direction: str
    natural_key: NaturalKey | None


@dataclass(frozen=True)
class IdentityDecision:
    stored_id: uuid.UUID | None
    action: str


def resolve_identity(candidate: Profile, stored: tuple[StoredIdentity, ...]) -> IdentityDecision:
    """Called again inside publication locks, never a concurrent-insert substitute.

    Stored immutable fallback keys may differ from current scientific observation
    time after an accepted stable-ID correction; never recompute them from science.
    """
    by_id = [
        row
        for row in stored
        if candidate.source_profile_id is not None
        and row.source_profile_id == candidate.source_profile_id
    ]
    by_key = [
        row
        for row in stored
        if candidate.natural_key is not None and row.natural_key == candidate.natural_key
    ]
    if len(by_id) > 1 or len(by_key) > 1:
        raise Rejection("identity_registry_conflict")
    if by_id:
        row = by_id[0]
        if by_key and by_key[0].id != row.id:
            raise Rejection("identity_conflict")
        if candidate.platform != row.platform:
            raise Rejection("identity_conflict")
        if (
            candidate.direction in ("A", "D")
            and row.direction in ("A", "D")
            and candidate.direction != row.direction
        ):
            raise Rejection("identity_conflict")
        return IdentityDecision(row.id, "match_stable_id")
    if by_key:
        row = by_key[0]
        if (
            candidate.source_profile_id is not None
            and row.source_profile_id is not None
            and candidate.source_profile_id != row.source_profile_id
        ):
            raise Rejection("identity_conflict")
        return IdentityDecision(
            row.id,
            "attach_stable_alias"
            if candidate.source_profile_id is not None and row.source_profile_id is None
            else "match_natural_key",
        )
    if candidate.source_profile_id is None:
        key = candidate.natural_key
        if key is None:
            raise Rejection("incomplete_fallback_identity")
        for row in stored:
            old = row.natural_key
            if (
                row.source_profile_id is None
                and old is not None
                and (old[0], old[1], old[2], old[4]) == (key[0], key[1], key[2], key[4])
            ):
                raise Rejection("fallback_observation_time_correction")
    return IdentityDecision(None, "insert_identity")
