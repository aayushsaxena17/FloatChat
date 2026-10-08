"""In-memory candidate set of one chunk: identity and revision decisions before staging.

stage1-v4: the chunk's mapped profiles stay in memory (bounded by the chunk caps) and are
resolved against the database with two batched reads: stored identities, then stored
hashes and revisions. Nothing is re-encoded or re-hashed: the canonical bytes and hash
come from the mapper. The retained population of a slot is never loaded; the set exposes
only this chunk's own accepted profiles per slot (the content of one published part).
The spool confers no publication authority; SQL rechecks identities and revisions.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .argovis import VARIABLES, Profile
from .identity import StoredIdentity, resolve_identity
from .numeric import CanonicalBudget, Rejection, ScientificNumber
from .planning import timestamp
from .revisions import Revision, compare
from .workflow import StoredState, owner_slot, staged_candidate, staging_table

CANONICAL_LIMIT = 256 * 1024**2
PROFILE_LIMIT = 2000
LEVEL_LIMIT = 2_000_000

# One query for all candidate identities, one for the hashes of the stored ids found.
IdentityBatch = Callable[[Sequence[Profile]], Mapping[str, tuple[StoredIdentity, ...]]]
HashLookup = Callable[[Sequence[uuid.UUID]], Mapping[uuid.UUID, StoredState]]


def revision_json(revision: Revision | None) -> str:
    return json.dumps(
        None
        if revision is None
        else {
            "kind": revision.kind,
            "components": {key: instant.isoformat() for key, instant in revision.components},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def parse_revision(value: Mapping[str, Any] | None) -> Revision | None:
    """Inverse of revision_json for a decoded value (also the stored jsonb)."""
    if value is None:
        return None
    return Revision(
        value["kind"],
        tuple(sorted((key, timestamp(instant)) for key, instant in value["components"].items())),
    )


def restore_profile(
    canonical: bytes,
    digest: str,
    source_id: str | None,
    revision: str,
    *,
    budget: CanonicalBudget | None = None,
    verify_encoding: bool = True,
) -> Profile:
    if len(canonical) > 16 * 1024**2:
        raise Rejection(
            "canonical_output_limit",
            resource={
                "scope": "profile",
                "operation": "readback",
                "limit_bytes": 16 * 1024**2,
                "used_bytes": 0,
                "requested_bytes": len(canonical),
            },
        )
    verified_hash = hashlib.sha256(canonical).hexdigest()
    if verified_hash != digest:
        raise Rejection("stored_scientific_hash_mismatch")
    content = json.loads(canonical)
    encoded, actual = (
        (budget or CanonicalBudget()).encode(content)
        if verify_encoding
        else (canonical, verified_hash)
    )
    if actual != digest or encoded != canonical:
        raise Rejection("stored_scientific_hash_mismatch")

    def number(value: dict[str, Any]) -> ScientificNumber:
        exact = value["exact"]
        return ScientificNumber(
            None if exact is None else float(Decimal(exact)),
            exact,
            value["missing_reason"],
            value["nonfinite_kind"],
            tuple(value["flags"]),
        )

    levels = []
    for level in content["levels"]:
        row = dict(level)
        for variable in VARIABLES:
            for suffix in ("", "_adjusted", "_error", "_original_error"):
                value = level[variable + suffix]
                row[variable + suffix] = None if value is None else number(value).value
        levels.append(row)
    return Profile(
        source_id,
        content["platform"],
        content["cycle"],
        content["direction"],
        content["observed_at"],
        number(content["longitude"]),
        number(content["latitude"]),
        parse_revision(json.loads(revision)),
        tuple(levels),
        canonical,
        digest,
        0,
    )


def merge_parts(
    tables: Sequence[pa.Table], manifest: Sequence[Mapping[str, Any]]
) -> Iterator[tuple[uuid.UUID, Profile]]:
    """The slot members held by parts/snapshots (oldest first), as profiles in id order.

    A row is a member only if its (profile_id, profile_hash) is in the slot manifest: a
    replaced or moved profile keeps its old rows in an older part. If the same pair is in
    several objects the newest wins. Every profile is rebuilt from its Parquet rows and
    checked against profile_hash (restore_profile), the level count against the manifest.
    """
    wanted = {f"{item['profile_id']}|{item['hash']}": item["levels"] for item in manifest}
    taken: set[str] = set()
    chosen: list[pa.Table] = []
    for table in reversed(tables):
        keys = pc.binary_join_element_wise(table["profile_id"], table["profile_hash"], "|")
        present = (set(pc.unique(keys).to_pylist()) & wanted.keys()) - taken
        if present:
            chosen.append(table.filter(pc.is_in(keys, value_set=pa.array(sorted(present)))))
            taken |= present
    if taken != wanted.keys():
        raise Rejection("stored_snapshot_membership_mismatch")
    if not chosen:
        return
    merged = pa.concat_tables(chosen).sort_by(
        [("profile_id", "ascending"), ("level_index", "ascending")]
    )
    counts = pc.value_counts(merged["profile_id"])
    start = 0
    for identifier, count in sorted(
        zip(counts.field("values").to_pylist(), counts.field("counts").to_pylist(), strict=True)
    ):
        block = merged.slice(start, count)
        start += count
        digest = block["profile_hash"][0].as_py()
        if wanted[f"{identifier}|{digest}"] != count:
            raise Rejection("stored_snapshot_membership_mismatch")
        content = json.loads(block["profile_content"][0].as_py())
        content["levels"] = [json.loads(text) for text in block["canonical_level"].to_pylist()]
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
        yield (
            uuid.UUID(identifier),
            restore_profile(
                canonical.encode(),
                digest,
                block["source_profile_id"][0].as_py(),
                "null",
                verify_encoding=False,
            ),
        )


@dataclass
class _Entry:
    ordinal: int
    profile: Profile
    raw: uuid.UUID
    profile_id: uuid.UUID | None = None
    outcome: str | None = None
    slot: str | None = None


class ProfileSpool:
    """Candidates of one chunk, in occurrence order, with their resolved outcomes.

    Accepted means outcome insert or newer. For a profile accepted twice in one chunk
    only the last accepted version is this chunk's content for its slot.
    """

    def __init__(self) -> None:
        self.entries: list[_Entry] = []
        self.by_identity: dict[str, _Entry] = {}
        self.incoming_bytes = self.incoming_levels = 0
        self.changed_slots: set[str] = set()
        self.conflicts: list[tuple[int, dict[str, Any]]] = []
        self.identities: dict[uuid.UUID, StoredIdentity] = {}
        self.outcomes: list[tuple[int, str, str, int]] = []
        self.accepted: dict[uuid.UUID, _Entry] = {}
        # Stored state (before this chunk) of the profiles an accepted candidate replaces.
        self.replaced: dict[uuid.UUID, StoredState] = {}

    def __enter__(self) -> "ProfileSpool":
        return self

    def __exit__(self, *args: Any) -> None:
        self.entries.clear()
        self.by_identity.clear()
        self.accepted.clear()

    def add(self, profile: Profile, raw: uuid.UUID, ordinal: int) -> None:
        self.incoming_bytes += len(profile.canonical_bytes)
        self.incoming_levels += len(profile.levels)
        if (
            self.incoming_bytes > CANONICAL_LIMIT
            or self.incoming_levels > LEVEL_LIMIT
            or not 0 <= ordinal < PROFILE_LIMIT
        ):
            raise Rejection("chunk_scientific_resource_limit")
        previous = self.by_identity.get(profile.identity)
        if previous is not None:
            if (previous.profile.content_hash, previous.profile.revision) != (
                profile.content_hash,
                profile.revision,
            ):
                raise Rejection("conflicting_duplicate_profile")
            self.outcomes.append(
                (ordinal, profile.identity, "identical_duplicate", len(profile.levels))
            )
            return
        entry = _Entry(ordinal, profile, raw)
        self.entries.append(entry)
        self.by_identity[profile.identity] = entry

    def prepare(self, identities: IdentityBatch, hashes: HashLookup) -> None:
        found = identities([entry.profile for entry in self.entries])
        for entry in self.entries:
            for stored in found.get(entry.profile.identity, ()):
                self.identities.setdefault(stored.id, stored)
        if len(self.identities) > 100000:
            raise Rejection("identity_registry_limit")
        states = hashes(list(self.identities)) if self.identities else {}
        for entry in self.entries:
            profile = entry.profile
            identity = resolve_identity(profile, tuple(self.identities.values()))
            identifier = identity.stored_id or uuid.uuid4()
            stored_state = None if identity.stored_id is None else states.get(identity.stored_id)
            if identity.stored_id is not None and stored_state is None:
                raise Rejection("publication_base_changed")
            local = self.accepted.get(identifier)
            previous_hash: str | None = None
            previous_revision: Revision | None = None
            if local is not None:
                previous_hash, previous_revision = (
                    local.profile.content_hash,
                    local.profile.revision,
                )
            elif stored_state is not None:
                previous_hash, previous_revision = stored_state.content_hash, stored_state.revision
            outcome = compare(
                profile.content_hash, profile.revision, previous_hash, previous_revision
            )
            if outcome == "revision_conflict":
                self.outcomes.append(
                    (entry.ordinal, profile.identity, outcome, len(profile.levels))
                )
                self.conflicts.append(
                    (
                        entry.ordinal,
                        {
                            "stored_profile_id": str(identifier),
                            "incoming_hash": profile.content_hash,
                            "incoming_revision": json.loads(revision_json(profile.revision)),
                            "stored_hash": previous_hash,
                            "stored_revision": None
                            if previous_hash is None
                            else json.loads(revision_json(previous_revision)),
                        },
                    )
                )
                raise Rejection("revision_conflict")
            if identity.stored_id is None:
                self.identities[identifier] = StoredIdentity(
                    identifier,
                    profile.platform,
                    profile.source_profile_id,
                    profile.cycle,
                    profile.direction,
                    profile.natural_key,
                )
            elif identity.action == "attach_stable_alias":
                self.identities[identifier] = replace(
                    self.identities[identifier], source_profile_id=profile.source_profile_id
                )
            entry.profile_id, entry.outcome = identifier, outcome
            self.outcomes.append((entry.ordinal, profile.identity, outcome, len(profile.levels)))
            if outcome in ("insert", "newer"):
                if stored_state is not None:
                    self.changed_slots.add(stored_state.slot)
                    self.replaced.setdefault(identifier, stored_state)
                if local is not None and local.slot is not None:
                    self.changed_slots.add(local.slot)
                entry.slot = owner_slot(profile)
                self.changed_slots.add(entry.slot)
                self.accepted[identifier] = entry

    def profiles(self, slot: str) -> Iterator[tuple[uuid.UUID, Profile]]:
        """Own accepted profiles of the slot in profile_id order: the content of its part."""
        for identifier in sorted(self.accepted):
            entry = self.accepted[identifier]
            if entry.slot == slot:
                yield identifier, entry.profile

    def departed(self, slot: str) -> list[StoredState]:
        """Stored profiles of the slot that an accepted candidate replaces or moves away."""
        return [state for state in self.replaced.values() if state.slot == slot]

    def candidates(self) -> Iterator[dict[str, Any]]:
        for entry in self.entries:
            if entry.profile_id is None:
                raise Rejection("unprepared_spool")
            yield {
                "occurrence_index": entry.ordinal,
                **staged_candidate(entry.profile, entry.profile_id, entry.raw),
            }

    def level_tables(self) -> Iterator[pa.Table]:
        """Typed level rows of every candidate whose levels SQL will insert."""
        for entry in self.entries:
            if entry.outcome in ("insert", "newer"):
                yield staging_table(entry.profile, entry.ordinal)

    def membership(self, slot: str) -> list[dict[str, Any]]:
        result = []
        for identifier, profile in self.profiles(slot):
            result.append(
                {
                    "profile_id": str(identifier),
                    "hash": profile.content_hash,
                    "levels": len(profile.levels),
                }
            )
            if len(result) > 100000:
                raise Rejection("snapshot_profile_limit")
        return result
