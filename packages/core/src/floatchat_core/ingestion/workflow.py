"""Deterministic publication candidates and full retained snapshot preview."""

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .argovis import Profile
from .identity import StoredIdentity, resolve_identity
from .numeric import Rejection
from .planning import GEOMETRY_VERSION, Tile, month_start, timestamp
from .revisions import compare


def owner_slot(profile: Profile) -> str:
    longitude, latitude = (
        Decimal(profile.longitude.exact or "NaN"),
        Decimal(profile.latitude.exact or "NaN"),
    )
    if not (20 <= longitude <= 120 and -60 <= latitude <= 30):
        raise Rejection("candidate_outside_region")
    west = 110 if longitude == 120 else int((longitude - 20) // 10) * 10 + 20
    south = 20 if latitude == 30 else int((latitude + 60) // 10) * 10 - 60
    tile = Tile(west, south)
    month = month_start(timestamp(profile.observed_at)).strftime("%Y-%m")
    return (
        f"argovis/core/{month}/{tile.west}:{tile.south}/{GEOMETRY_VERSION}/"
        "argovis-core-v1/scientific-json-v2"
    )


def staged_candidate(
    profile: Profile, proposed_id: uuid.UUID, raw_manifest_id: uuid.UUID
) -> dict[str, Any]:
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
        "levels": list(profile.levels),
    }


@dataclass(frozen=True)
class StoredScience:
    identity: StoredIdentity
    profile: Profile


@dataclass(frozen=True)
class Preview:
    candidates: tuple[dict[str, Any], ...]
    scientific_profiles: dict[uuid.UUID, Profile]
    changed_slots: frozenset[str]
    outcomes: tuple[tuple[str, str], ...]

    def membership(self, slot: str) -> list[dict[str, Any]]:
        return [
            {
                "profile_id": str(identifier),
                "hash": profile.content_hash,
                "levels": len(profile.levels),
            }
            for identifier, profile in sorted(self.scientific_profiles.items())
            if owner_slot(profile) == slot
        ]


def preview(
    incoming: tuple[tuple[Profile, uuid.UUID], ...], stored: tuple[StoredScience, ...]
) -> Preview:
    """Stored must include affected slots' full science, not an eligibility projection.

    The SQL procedure rechecks identities, revisions, manifests and slot versions;
    this preview never confers publication authority.
    """
    identities = [row.identity for row in stored]
    scientific = {row.identity.id: row.profile for row in stored}
    candidates: list[dict[str, Any]] = []
    changed: set[str] = set()
    outcomes: list[tuple[str, str]] = []
    seen: dict[str, Profile] = {}
    for profile, raw_id in incoming:
        prior = seen.get(profile.identity)
        if prior is not None:
            if prior.content_hash != profile.content_hash or prior.revision != profile.revision:
                raise Rejection("conflicting_duplicate_profile")
            outcomes.append((profile.identity, "identical_duplicate"))
            continue
        seen[profile.identity] = profile
        identity = resolve_identity(profile, tuple(identities))
        identifier = identity.stored_id or uuid.uuid4()
        previous = scientific.get(identifier)
        outcome = compare(
            profile.content_hash,
            profile.revision,
            None if previous is None else previous.content_hash,
            None if previous is None else previous.revision,
        )
        if outcome == "revision_conflict":
            raise Rejection("revision_conflict")
        if identity.stored_id is None:
            identities.append(
                StoredIdentity(
                    identifier,
                    profile.platform,
                    profile.source_profile_id,
                    profile.cycle,
                    profile.direction,
                    profile.natural_key,
                )
            )
        elif identity.action == "attach_stable_alias":
            identities = [
                StoredIdentity(
                    row.id,
                    row.platform,
                    profile.source_profile_id,
                    row.cycle,
                    row.direction,
                    row.natural_key,
                )
                if row.id == identifier
                else row
                for row in identities
            ]
        candidates.append(staged_candidate(profile, identifier, raw_id))
        outcomes.append((profile.identity, outcome))
        if outcome in ("insert", "newer"):
            if previous is not None:
                changed.add(owner_slot(previous))
            changed.add(owner_slot(profile))
            scientific[identifier] = profile
    return Preview(tuple(candidates), scientific, frozenset(changed), tuple(outcomes))


def copy_rows(
    connection: Any,
    run_id: uuid.UUID,
    chunk_id: uuid.UUID,
    fence: int,
    candidates: Iterable[dict[str, Any]],
) -> None:
    """Client COPY only, with fixed migration-owned table/column identifiers."""
    with connection.cursor() as cursor:
        with cursor.copy(
            "COPY app.ingestion_staging(run_id,chunk_id,fence,occurrence_index,candidate) "
            "FROM STDIN"
        ) as copy:
            for index, candidate in enumerate(candidates):
                if index >= 2000:
                    raise Rejection("profile_count_limit")
                occurrence = candidate.get("occurrence_index", index)
                if type(occurrence) is not int or not 0 <= occurrence < 2000:
                    raise Rejection("invalid_occurrence_index")
                copy.write_row(
                    (run_id, chunk_id, fence, occurrence, json.dumps(candidate, allow_nan=False))
                )
