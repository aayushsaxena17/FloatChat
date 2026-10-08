"""Private disk staging: one decoded scientific profile in memory at a time.

The incoming budget and retained snapshot population are distinct. Retained
observations are never removed by a new rolling cutoff or an empty refresh.
The spool confers no publication authority; SQL rechecks the preview at commit.
"""

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from .argovis import VARIABLES, Profile
from .identity import StoredIdentity, resolve_identity
from .numeric import CanonicalBudget, Rejection, ScientificNumber
from .planning import timestamp
from .revisions import Revision, compare
from .workflow import StoredScience, owner_slot, staged_candidate


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
    vector = json.loads(revision)
    return Profile(
        source_id,
        content["platform"],
        content["cycle"],
        content["direction"],
        content["observed_at"],
        number(content["longitude"]),
        number(content["latitude"]),
        None
        if vector is None
        else Revision(
            vector["kind"],
            tuple(sorted((key, timestamp(value)) for key, value in vector["components"].items())),
        ),
        tuple(levels),
        canonical,
        digest,
        0,
    )


class ProfileSpool:
    def __init__(
        self,
        path: Path,
        *,
        disk_limit: int = 10 * 1024**3,
        budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]] | None = None,
    ) -> None:
        if path.exists() or not 0 < disk_limit <= 10 * 1024**3:
            raise Rejection("invalid_private_spool")
        # Exclusive file creation and restrictive mode precede SQLite opening it.
        with path.open("xb"):
            path.chmod(0o600)
        self.path, self.disk_limit = path, disk_limit
        self.budget_factory = budget_factory or (lambda: nullcontext(CanonicalBudget()))
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-8192")
        self.connection.execute(f"PRAGMA max_page_count={max(1, disk_limit // 4096)}")
        self.connection.executescript("""
          CREATE TABLE incoming(ordinal INTEGER PRIMARY KEY, identity TEXT UNIQUE,
            canonical BLOB NOT NULL, hash TEXT NOT NULL, source_id TEXT, revision TEXT NOT NULL,
            raw_id TEXT NOT NULL, profile_id TEXT, outcome TEXT);
          CREATE TABLE science(profile_id TEXT PRIMARY KEY, slot TEXT NOT NULL,
            canonical BLOB NOT NULL, hash TEXT NOT NULL, source_id TEXT, revision TEXT NOT NULL,
            overlay INTEGER NOT NULL);
          CREATE INDEX science_slot ON science(slot,profile_id);
        """)
        self.incoming_bytes = self.incoming_levels = self.disk_bytes = 0
        self.changed_slots: set[str] = set()
        self.conflicts: list[tuple[int, dict[str, Any]]] = []
        self.identities: dict[uuid.UUID, StoredIdentity] = {}
        self.outcomes: list[tuple[int, str, str, int]] = []
        # Certification lives only for this private spool/process. Every reuse
        # still checks the actual bytes' SHA-256; recovery starts with no cache.
        self._verified_canonical: set[str] = set()

    def __enter__(self) -> "ProfileSpool":
        return self

    def __exit__(self, *args: Any) -> None:
        self.connection.close()

    def charge(self, count: int) -> None:
        if self.disk_bytes + count > self.disk_limit:
            raise Rejection("private_spool_size_limit")
        self.disk_bytes += count

    def restore(self, canonical: bytes, digest: str, source: str | None, revision: str) -> Profile:
        if digest in self._verified_canonical:
            return restore_profile(canonical, digest, source, revision, verify_encoding=False)
        with self.budget_factory() as budget:
            profile = restore_profile(canonical, digest, source, revision, budget=budget)
        if len(self._verified_canonical) >= 102000:
            raise Rejection("snapshot_profile_limit")
        self._verified_canonical.add(digest)
        return profile

    def add(self, profile: Profile, raw: uuid.UUID, ordinal: int) -> None:
        self.incoming_bytes += len(profile.canonical_bytes)
        self.incoming_levels += len(profile.levels)
        if (
            self.incoming_bytes > 256 * 1024**2
            or self.incoming_levels > 2_000_000
            or not 0 <= ordinal < 2000
        ):
            raise Rejection("chunk_scientific_resource_limit")
        previous = self.connection.execute(
            "SELECT hash,revision FROM incoming WHERE identity=?", (profile.identity,)
        ).fetchone()
        if previous is not None:
            if previous != (profile.content_hash, revision_json(profile.revision)):
                raise Rejection("conflicting_duplicate_profile")
            self.outcomes.append(
                (ordinal, profile.identity, "identical_duplicate", len(profile.levels))
            )
            return
        self.charge(len(profile.canonical_bytes))
        self.connection.execute(
            "INSERT INTO incoming VALUES(?,?,?,?,?,?,?,NULL,NULL)",
            (
                ordinal,
                profile.identity,
                profile.canonical_bytes,
                profile.content_hash,
                profile.source_profile_id,
                revision_json(profile.revision),
                str(raw),
            ),
        )

    def prepare(
        self,
        lookup: Callable[[Profile], tuple[StoredScience, ...]],
        *,
        identity_lookup: Callable[[Profile], tuple[StoredIdentity, ...]] | None = None,
        load_science: Callable[[uuid.UUID], Profile] | None = None,
    ) -> None:
        for row in self.connection.execute("SELECT * FROM incoming ORDER BY ordinal"):
            ordinal, key, canonical, digest, source, revision, _, _, _ = row
            profile = self.restore(canonical, digest, source, revision)
            existing = () if identity_lookup is not None else lookup(profile)
            registry = (
                tuple(row.identity for row in existing)
                if identity_lookup is None
                else identity_lookup(profile)
            )
            for stored in registry:
                self.identities.setdefault(stored.id, stored)
            if len(self.identities) > 100000:
                raise Rejection("identity_registry_limit")
            identity = resolve_identity(profile, tuple(self.identities.values()))
            identifier = identity.stored_id or uuid.uuid4()
            previous = next((r.profile for r in existing if r.identity.id == identifier), None)
            if load_science is not None and identity.stored_id is not None:
                previous = load_science(identity.stored_id)
            local = self.connection.execute(
                "SELECT canonical,hash,source_id,revision FROM science WHERE profile_id=?",
                (str(identifier),),
            ).fetchone()
            if local is not None:
                previous = self.restore(*local)
            outcome = compare(
                digest,
                profile.revision,
                None if previous is None else previous.content_hash,
                None if previous is None else previous.revision,
            )
            if outcome == "revision_conflict":
                self.outcomes.append((ordinal, key, outcome, len(profile.levels)))
                self.conflicts.append(
                    (
                        ordinal,
                        {
                            "stored_profile_id": str(identifier),
                            "incoming_hash": digest,
                            "incoming_revision": json.loads(revision_json(profile.revision)),
                            "stored_hash": None if previous is None else previous.content_hash,
                            "stored_revision": None
                            if previous is None
                            else json.loads(revision_json(previous.revision)),
                        },
                    )
                )
                raise Rejection("revision_conflict")
            if identity.stored_id is None:
                self.identities[identifier] = StoredIdentity(
                    identifier,
                    profile.platform,
                    source,
                    profile.cycle,
                    profile.direction,
                    profile.natural_key,
                )
            elif identity.action == "attach_stable_alias":
                self.identities[identifier] = replace(
                    self.identities[identifier], source_profile_id=source
                )
            self.connection.execute(
                "UPDATE incoming SET profile_id=?,outcome=? WHERE ordinal=?",
                (str(identifier), outcome, ordinal),
            )
            self.outcomes.append((ordinal, key, outcome, len(profile.levels)))
            if outcome in ("insert", "newer"):
                if previous is not None:
                    self.changed_slots.add(owner_slot(previous))
                slot = owner_slot(profile)
                self.changed_slots.add(slot)
                self.charge(len(canonical))
                self.connection.execute(
                    "INSERT OR REPLACE INTO science VALUES(?,?,?,?,?,?,1)",
                    (str(identifier), slot, canonical, digest, source, revision),
                )

    def retain(self, stored: Iterable[StoredScience]) -> None:
        for item in stored:
            identifier, profile = item.identity.id, item.profile
            if owner_slot(profile) not in self.changed_slots:
                raise Rejection("unexpected_retained_slot")
            exists = self.connection.execute(
                "SELECT 1 FROM science WHERE profile_id=?", (str(identifier),)
            ).fetchone()
            if exists:
                continue  # A newer accepted ownership correction overrides the old slot.
            self.charge(len(profile.canonical_bytes))
            self.connection.execute(
                "INSERT INTO science VALUES(?,?,?,?,?,?,0)",
                (
                    str(identifier),
                    owner_slot(profile),
                    profile.canonical_bytes,
                    profile.content_hash,
                    profile.source_profile_id,
                    revision_json(profile.revision),
                ),
            )
        self.connection.commit()

    def profiles(self, slot: str) -> Iterator[tuple[uuid.UUID, Profile]]:
        for row in self.connection.execute(
            "SELECT profile_id,canonical,hash,source_id,revision FROM science "
            "WHERE slot=? ORDER BY profile_id",
            (slot,),
        ):
            yield uuid.UUID(row[0]), self.restore(*row[1:])

    def candidates(self) -> Iterator[dict[str, Any]]:
        for row in self.connection.execute("SELECT * FROM incoming ORDER BY ordinal"):
            ordinal, _, canonical, digest, source, revision, raw, identifier, _ = row
            if identifier is None:
                raise Rejection("unprepared_spool")
            yield {
                "occurrence_index": ordinal,
                **staged_candidate(
                    self.restore(canonical, digest, source, revision),
                    uuid.UUID(identifier),
                    uuid.UUID(raw),
                ),
            }

    def write_candidates(self, path: Path) -> None:
        # Canonical accounting completes before COPY takes the run-control lock.
        # The COPY reader does no profile decoding or nested authority writes.
        with path.open("xb") as output:
            path.chmod(0o600)
            for candidate in self.candidates():
                data = json.dumps(candidate, separators=(",", ":"), allow_nan=False).encode()
                if len(data) > 64 * 1024**2:
                    raise Rejection("staging_resource_limit")
                self.charge(len(data))
                output.write(str(candidate["occurrence_index"]).encode() + b"\t" + data + b"\n")

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
