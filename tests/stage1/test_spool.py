import copy
import hashlib
import io
import json
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.identity import StoredIdentity
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import write_snapshot
from floatchat_core.ingestion.planning import ACCEPTANCE_REFERENCE, Interval, RunPolicy, timestamp
from floatchat_core.ingestion.processor import Processor
from floatchat_core.ingestion.repository import (
    SAFE_DATABASE_CATEGORIES,
    Authority,
    Repository,
    SlotState,
)
from floatchat_core.ingestion.spool import ProfileSpool, merge_parts
from floatchat_core.ingestion.workflow import (
    MEASUREMENT_COLUMNS,
    STAGING_SCHEMA,
    StoredState,
    owner_slot,
    staged_candidate,
    staging_table,
)

ROOT = Path(__file__).resolve().parents[2]


def profile(wire, metadata):
    return map_profile(decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget())


def newer(value):
    return replace(
        value,
        revision=replace(
            value.revision,
            components=tuple(
                (key, stamp + timedelta(days=1)) for key, stamp in value.revision.components
            ),
        ),
    )


class Database:
    """Stored profiles as the two batched repository reads see them; counts calls."""

    def __init__(self, *stored):
        self.rows = {}
        self.identity_calls = []
        self.hash_calls = []
        for value in stored:
            self.add(value)

    def add(self, value):
        identifier = uuid.uuid4()
        self.rows[identifier] = (
            StoredIdentity(
                identifier,
                value.platform,
                value.source_profile_id,
                value.cycle,
                value.direction,
                value.natural_key,
            ),
            StoredState(
                value.content_hash,
                value.revision,
                timestamp(value.observed_at),
                Decimal(value.longitude.exact),
                Decimal(value.latitude.exact),
            ),
        )
        return identifier

    def identities(self, profiles):
        self.identity_calls.append(len(profiles))
        return {
            p.identity: tuple(
                identity
                for identity, _ in self.rows.values()
                if (
                    p.source_profile_id is not None
                    and identity.source_profile_id == p.source_profile_id
                )
                or (identity.platform, identity.cycle, identity.direction)
                == (p.platform, p.cycle, p.direction)
            )
            for p in profiles
        }

    def hashes(self, ids):
        self.hash_calls.append(sorted(ids))
        return {identifier: self.rows[identifier][1] for identifier in ids}

    def prepare(self, spool):
        spool.prepare(self.identities, self.hashes)


def test_B01_N08_chunk_caps_checked_before_a_candidate_is_kept(wire, linked_metadata):
    value = profile(wire, linked_metadata)
    with ProfileSpool() as spool:
        spool.incoming_bytes = 256 * 1024**2
        with pytest.raises(Rejection, match="chunk_scientific_resource_limit"):
            spool.add(value, uuid.uuid4(), 0)
        assert spool.entries == []
    with ProfileSpool() as spool:
        spool.incoming_levels = 2_000_000
        with pytest.raises(Rejection, match="chunk_scientific_resource_limit"):
            spool.add(value, uuid.uuid4(), 0)
    with ProfileSpool() as spool:
        with pytest.raises(Rejection, match="chunk_scientific_resource_limit"):
            spool.add(value, uuid.uuid4(), 2000)
        spool.add(value, uuid.uuid4(), 1999)


def test_P01_batched_reads_once_and_no_retained_population(wire, linked_metadata):
    values = []
    for number in range(3):
        wire["_id"] = f"batched-{number}"
        wire["cycle_number"] = 100 + number
        values.append(profile(wire, linked_metadata))
    database = Database(values[0])
    with ProfileSpool() as spool:
        for index, value in enumerate(values):
            spool.add(value, uuid.uuid4(), index)
        database.prepare(spool)
        # One identity read for the whole chunk, one hash read for the ids it found.
        assert database.identity_calls == [3]
        assert database.hash_calls == [sorted(database.rows)]
        assert [row[2] for row in spool.outcomes] == ["noop", "insert", "insert"]
        # Only the two inserted profiles are this chunk's content; the stored one is not.
        slot = owner_slot(values[1])
        assert len(spool.membership(slot)) == 2
        assert spool.departed(slot) == []


def test_T06_F02_part_holds_only_own_profiles_and_names_what_it_replaces(
    tmp_path, wire, linked_metadata
):
    retained_wire = copy.deepcopy(wire)
    retained_wire["timestamp"] = "2025-10-01T00:00:00Z"
    retained_wire["_id"] = "retained-old"
    old = profile(retained_wire, linked_metadata)
    wire["timestamp"] = "2025-10-07T00:00:00Z"
    eligible = profile(wire, linked_metadata)
    initial = RunPolicy.capture(
        "normal", "synthetic-env", actual_now=timestamp("2026-10-01T00:00:00Z")
    )
    advanced = RunPolicy.capture(
        "normal", "synthetic-env", actual_now=timestamp("2026-10-06T00:00:00Z")
    )
    advanced.validate(
        Interval(timestamp("2025-10-06T00:00:00Z"), timestamp("2025-11-01T00:00:00Z"))
    )
    assert initial.eligible.contains(timestamp(old.observed_at))
    assert not advanced.eligible.contains(timestamp(old.observed_at))
    corrected_wire = copy.deepcopy(wire)
    corrected_wire["data"][0][0] += 1
    corrected_wire["data"] = [array[:2] for array in corrected_wire["data"]]
    corrected = newer(profile(corrected_wire, linked_metadata))
    database = Database(old, eligible)
    eligible_id = next(
        identifier
        for identifier, (identity, _) in database.rows.items()
        if identity.source_profile_id == eligible.source_profile_id
    )
    with ProfileSpool() as spool:
        spool.add(corrected, uuid.uuid4(), 0)
        database.prepare(spool)
        slot = owner_slot(corrected)
        assert spool.outcomes[0][2] == "newer"
        # The retained, older observation is not loaded, listed or rewritten: the part has
        # exactly the corrected profile (2 levels); the manifest edit is SQL's.
        assert [identifier for identifier, _ in spool.profiles(slot)] == [eligible_id]
        assert spool.membership(slot) == [
            {"profile_id": str(eligible_id), "hash": corrected.content_hash, "levels": 2}
        ]
        assert [state.content_hash for state in spool.departed(slot)] == [eligible.content_hash]
        evidence = write_snapshot(
            tmp_path / "part.parquet", spool.profiles(slot), deadline=time.monotonic() + 20
        )
        assert evidence["profiles"] == 1 and evidence["rows"] == 2
        assert spool.changed_slots == {slot}


def test_P09c_ownership_correction_leaves_old_slot_without_a_part(wire, linked_metadata):
    old = profile(wire, linked_metadata)
    wire["geolocation"]["coordinates"] = [80, 10]
    corrected = newer(profile(wire, linked_metadata))
    database = Database(old)
    identifier = next(iter(database.rows))
    with ProfileSpool() as spool:
        spool.add(corrected, uuid.uuid4(), 0)
        database.prepare(spool)
        assert spool.changed_slots == {owner_slot(old), owner_slot(corrected)}
        # Old slot: nothing to publish, its manifest loses the profile (SQL), receipts
        # see one departure. New slot: a part with the moved profile.
        assert spool.membership(owner_slot(old)) == []
        assert len(spool.departed(owner_slot(old))) == 1
        assert spool.membership(owner_slot(corrected))[0]["profile_id"] == str(identifier)
        assert spool.departed(owner_slot(corrected)) == []


def test_F02_duplicate_occurrences_keep_indices_and_do_not_duplicate_science(wire, linked_metadata):
    first = profile(wire, linked_metadata)
    wire["_id"] = "second-profile"
    wire["cycle_number"] += 1
    second = profile(wire, linked_metadata)
    with ProfileSpool() as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(first, uuid.uuid4(), 1)
        spool.add(second, uuid.uuid4(), 2)
        Database().prepare(spool)
        candidates = list(spool.candidates())
        assert [row["occurrence_index"] for row in candidates] == [0, 2]
        assert len(spool.membership(owner_slot(first))) == 2
        assert spool.outcomes[0] == (1, first.identity, "identical_duplicate", 3)


def test_F02_conflicting_duplicate_occurrence_is_rejected(wire, linked_metadata):
    first = profile(wire, linked_metadata)
    wire["data"][0][0] += 1
    other = profile(wire, linked_metadata)
    assert other.identity == first.identity and other.content_hash != first.content_hash
    with ProfileSpool() as spool:
        spool.add(first, uuid.uuid4(), 0)
        with pytest.raises(Rejection, match="conflicting_duplicate_profile"):
            spool.add(other, uuid.uuid4(), 1)


def test_I03_spool_rejects_two_stable_ids_for_one_natural_identity(wire, linked_metadata):
    wire["profile_direction"] = "A"
    first = profile(wire, linked_metadata)
    wire["_id"] = "different-stable-id"
    second = profile(wire, linked_metadata)
    with ProfileSpool() as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(second, uuid.uuid4(), 1)
        with pytest.raises(Rejection, match="identity_conflict"):
            Database().prepare(spool)


def test_R03_revision_conflict_records_outcome_and_evidence(wire, linked_metadata):
    stored = profile(wire, linked_metadata)
    wire["data"][0][0] += 1
    conflicting = profile(wire, linked_metadata)  # same revision vector, different hash
    database = Database(stored)
    with ProfileSpool() as spool:
        spool.add(conflicting, uuid.uuid4(), 0)
        with pytest.raises(Rejection, match="revision_conflict"):
            database.prepare(spool)
        assert spool.outcomes == [(0, conflicting.identity, "revision_conflict", 3)]
        evidence = spool.conflicts[0][1]
        assert evidence["stored_hash"] == stored.content_hash
        assert evidence["incoming_hash"] == conflicting.content_hash
        assert spool.changed_slots == set() and not list(spool.level_tables())


def test_P06_staging_rows_are_slim_and_levels_travel_typed(wire, linked_metadata):
    first = profile(wire, linked_metadata)
    wire["_id"] = "unchanged-profile"
    wire["cycle_number"] += 1
    second = profile(wire, linked_metadata)
    database = Database(second)
    with ProfileSpool() as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(second, uuid.uuid4(), 1)
        database.prepare(spool)
        assert [row[2] for row in spool.outcomes] == ["insert", "noop"]
        slim = list(spool.candidates())
        assert [row["occurrence_index"] for row in slim] == [0, 1]
        for row in slim:
            assert "levels" not in row and row["level_count"] == 3
            assert row["canonical"].encode() in (first.canonical_bytes, second.canonical_bytes)
        # Levels only for the candidate SQL will insert, as the typed columns of the table.
        tables = list(spool.level_tables())
        assert len(tables) == 1 and tables[0].schema.equals(STAGING_SCHEMA)
        table = tables[0]
        assert table["occurrence_index"].to_pylist() == [0, 0, 0]
        assert table["level_index"].to_pylist() == [0, 1, 2]
        for name, _ in MEASUREMENT_COLUMNS:
            assert table[name].to_pylist() == [level[name] for level in first.levels], name


def test_P06_staging_table_matches_the_migration_columns():
    sql = (ROOT / "infra/migrations/versions/0013_publication_v4.sql").read_text()
    block = sql[sql.index("CREATE UNLOGGED TABLE app.measurement_staging") :]
    block = block[: block.index("PRIMARY KEY")]
    declared = re.findall(r"^  (\w+) (app\.finite_float8|app\.qc_code|text|jsonb)", block, re.M)
    assert [name for name, _ in declared] == [name for name, _ in MEASUREMENT_COLUMNS]
    base = {"app.finite_float8": "float8", "app.qc_code": "text", "text": "text", "jsonb": "jsonb"}
    assert [base[kind] for _, kind in declared] == [kind for _, kind in MEASUREMENT_COLUMNS]
    core = (ROOT / "infra/migrations/versions/0002_ingestion_foundation.sql").read_text()
    core = core[core.index("CREATE TABLE app.core_measurement") :]
    core = core[: core.index("PRIMARY KEY(observation_month")]
    for name, _ in MEASUREMENT_COLUMNS:
        assert re.search(rf"\b{name} ", core), name


def test_staged_candidate_is_the_slim_row(wire, linked_metadata):
    value = profile(wire, linked_metadata)
    row = staged_candidate(value, uuid.uuid4(), uuid.uuid4())
    assert set(row) == {
        "proposed_profile_id",
        "source_profile_id",
        "platform",
        "cycle",
        "direction",
        "observed_at",
        "identity_observed_at",
        "canonical",
        "content_hash",
        "revision",
        "raw_manifest_id",
        "level_count",
    }
    assert row["level_count"] == len(value.levels)
    assert staging_table(value, 7).num_rows == len(value.levels)


def part_of(tmp_path, name, *entries):
    """A published part: write_snapshot of (id, profile) pairs in id order."""
    path = tmp_path / (name + ".parquet")
    evidence = write_snapshot(path, sorted(entries), deadline=time.monotonic() + 30)
    return pq.read_table(path), evidence


def test_P08_merge_applies_manifest_to_overlapping_parts(tmp_path, wire, linked_metadata):
    ids = [uuid.UUID(int=index + 1) for index in range(3)]
    values = []
    for number in range(3):
        wire["_id"] = f"merge-{number}"
        wire["cycle_number"] = 200 + number
        values.append(profile(wire, linked_metadata))
    # Part 1: A and B. Part 2 replaces B (new hash) and adds C. Manifest: A, B', C.
    replaced_wire = copy.deepcopy(wire)
    replaced_wire["_id"] = "merge-1"
    replaced_wire["cycle_number"] = 201
    replaced_wire["data"][0][0] += 1
    replaced = profile(replaced_wire, linked_metadata)
    one, _ = part_of(tmp_path, "one", (ids[0], values[0]), (ids[1], values[1]))
    two, _ = part_of(tmp_path, "two", (ids[1], replaced), (ids[2], values[2]))
    manifest = [
        {"profile_id": str(ids[0]), "hash": values[0].content_hash, "levels": 3},
        {"profile_id": str(ids[1]), "hash": replaced.content_hash, "levels": 3},
        {"profile_id": str(ids[2]), "hash": values[2].content_hash, "levels": 3},
    ]
    merged = list(merge_parts([one, two], manifest))
    assert [identifier for identifier, _ in merged] == ids
    assert [value.content_hash for _, value in merged] == [
        values[0].content_hash,
        replaced.content_hash,
        values[2].content_hash,
    ]
    for (_, rebuilt), original in zip(merged, (values[0], replaced, values[2]), strict=True):
        assert rebuilt.canonical_bytes == original.canonical_bytes
        assert rebuilt.levels == original.levels
        assert rebuilt.source_profile_id == original.source_profile_id
    snapshot, evidence = part_of(tmp_path, "snapshot", *merged)
    assert evidence["profiles"] == 3 and evidence["rows"] == 9
    assert snapshot.num_rows == 9
    # Old rows of the replaced profile stay in part one but are not members.
    assert one.num_rows == 6 and sum(len(value.levels) for _, value in merged) == 9
    # A manifest member without rows, or with another level count, never merges.
    with pytest.raises(Rejection, match="stored_snapshot_membership_mismatch"):
        list(merge_parts([one], manifest))
    wrong = [*manifest[:2], {**manifest[2], "levels": 4}]
    with pytest.raises(Rejection, match="stored_snapshot_membership_mismatch"):
        list(merge_parts([one, two], wrong))
    # The same pair in two objects (a reverted profile) yields one copy, newest wins.
    both = list(merge_parts([one, one], manifest[:1]))
    assert len(both) == 1 and len(both[0][1].levels) == 3


class FakeRepository:
    """Records what Processor.publish asks of the database; no SQL, no network."""

    def __init__(self, database, *, counts=None, fail_commits=0, west=70):
        self.database = database
        self.west = west
        self.counts = counts or {}  # slot -> (members, selected) stored now
        self.fail_commits = fail_commits
        self.calls = []
        self.transitions = []
        self.state = "validating"
        self.staged = []
        self.levels = []

    def chunk(self, identifier):
        return {
            "state": self.state,
            "requested_start": timestamp("2025-01-01T00:00:00Z"),
            "requested_end": timestamp("2025-01-07T00:00:00Z"),
            "tile": {"west": self.west, "south": 10, "width": 10, "height": 10},
        }

    def run(self, identifier):
        return {
            "run_reference_time_utc": ACCEPTANCE_REFERENCE,
            "mode": "acceptance",
            "environment_id": uuid.uuid4(),
        }

    @contextmanager
    def canonical_budget(self, authority):
        yield CanonicalBudget()

    def heartbeat(self, authority):
        self.calls.append("heartbeat")

    def identities_batch(self, profiles):
        self.calls.append("identities_batch")
        return self.database.identities(profiles)

    def science_hashes(self, ids):
        self.calls.append("science_hashes")
        return self.database.hashes(ids)

    def outcomes(self, authority, outcomes):
        self.outcome_rows = [dict(row) for row in outcomes]

    def accounting(self, authority, evidence):
        self.evidence = evidence

    def transition(self, authority, state, reason, evidence=None):
        self.transitions.append(state)

    def ensure_slot(self, authority, month, tile):
        self.calls.append("ensure_slot")
        return owner_slot_for(month, tile)

    def slot_state(self, authority, slots, piece, *, counts=()):
        self.calls.append(("slot_state", tuple(slots), tuple(counts)))
        return {
            slot: SlotState(
                4,
                *(self.counts[slot] if slot in counts else (None, None)),
            )
            for slot in slots
        }

    def prepare_intent(self, authority, intent, keys, bases, revisions):
        self.calls.append("prepare_intent")
        self.intent = {"id": intent, "keys": keys, "bases": bases}

    def stage_candidates(self, authority, candidates):
        self.calls.append("stage_candidates")
        self.staged = list(candidates)

    def stage_levels(self, authority, tables):
        self.calls.append("stage_levels")
        self.levels = list(tables)

    def commit(self, authority, intent, generations, receipts):
        self.calls.append("commit")
        self.generations, self.receipts = generations, receipts
        if self.fail_commits:
            self.fail_commits -= 1
            raise Rejection("publication_base_changed")


def owner_slot_for(month, tile):
    return (
        f"argovis/core/{month:%Y-%m}/{tile.west}:{tile.south}/indian-ocean-v1/"
        "argovis-core-v1/scientific-json-v2"
    )


class ObjectsStore:
    def __init__(self):
        self.data = {}

    def write_immutable(self, key, data, sha256_hex, deadline):
        assert hashlib.sha256(data).hexdigest() == sha256_hex
        self.data.setdefault(key, data)

    def stat(self, key, deadline):
        return {"bytes": len(self.data[key]), "sha256": None}

    def write_temporary(self, key, data, deadline):
        self.data[key] = data

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])

    def read(self, key, max_bytes, deadline):
        return self.data[key]


def processor_for(tmp_path, repository, documents, metadata):
    private = tmp_path / "private"
    private.mkdir(exist_ok=True)
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 1)
    store = ObjectsStore()
    processor = Processor(
        repository,
        repository,
        store,
        None,
        authority,
        private,
        deadline=time.monotonic() + 120,
    )
    processor.raw_ids = {"profile": str(uuid.uuid4())}
    processor.raw_paths = {"profile": private / "profile.json"}
    processor.raw_paths["profile"].write_bytes(json.dumps(documents).encode())
    for pointer, document in metadata.items():
        file = private / (uuid.uuid4().hex + ".json")
        file.write_bytes(json.dumps([document]).encode())
        processor.meta[pointer] = file
    processor.observed_profiles = len(documents)
    return processor, store


def test_P06_publish_writes_one_part_of_own_profiles_and_stages_slim_rows(
    tmp_path, wire, linked_metadata
):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    repository = FakeRepository(Database())
    processor, store = processor_for(tmp_path, repository, [wire], linked_metadata)
    assert processor.process() == "complete"
    (generation,) = repository.generations
    value = profile(wire, linked_metadata)
    assert generation["kind"] == "part" and generation["base_version"] == 4
    assert generation["logical_key"] == owner_slot(value)
    (entry,) = generation["membership_manifest"]
    assert entry["hash"] == value.content_hash and entry["levels"] == 3
    assert generation["profile_count"] == 1 and generation["row_count"] == 3
    assert "certificate" not in generation["verification_evidence"]
    assert store.data[generation["object_key"]] and generation["bytes"] > 0
    assert hashlib.sha256(store.data[generation["object_key"]]).hexdigest() == generation["sha256"]
    # The object is a single part: its rows are this profile's levels.
    assert pq.read_table(io.BytesIO(store.data[generation["object_key"]])).num_rows == 3
    # Slim staging: one candidate row without levels, one typed table of the 3 levels.
    assert len(repository.staged) == 1 and "levels" not in repository.staged[0]
    assert repository.staged[0]["level_count"] == 3
    assert [table.num_rows for table in repository.levels] == [3]
    # Receipts: the filled slot needs no stored-count read and carries no base version.
    (receipt,) = repository.receipts
    assert (receipt["fetch_disposition"], receipt["stored_disposition"]) == (
        "profiles_returned",
        "active_generation",
    )
    assert "base_version" not in receipt
    assert repository.calls.count("commit") == 1
    assert ("slot_state", (owner_slot(value),), ()) in repository.calls
    assert (
        repository.transitions == ["validating", "publishing"][1:]
        or "publishing" in repository.transitions
    )
    assert generation["id"] and repository.intent["keys"][0] == generation["object_key"]


def test_P06_rebuild_after_publication_base_changed_repeats_the_whole_publication(
    tmp_path, wire, linked_metadata
):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    repository = FakeRepository(Database(), fail_commits=2)
    processor, _ = processor_for(tmp_path, repository, [wire], linked_metadata)
    assert processor.process() == "complete"
    assert repository.calls.count("commit") == 3
    assert repository.calls.count("prepare_intent") == 3
    assert repository.calls.count("stage_levels") == 3
    # Four attempts at most, then the bounded-budget failure.
    exhausted = FakeRepository(Database(), fail_commits=10)
    again, _ = processor_for(tmp_path, exhausted, [wire], linked_metadata)
    with pytest.raises(Rejection, match="publication_base_changed"):
        again.publish()
    assert exhausted.calls.count("commit") == 4


def test_P09c_correction_moving_the_last_profile_publishes_a_manifest_only_slot(
    tmp_path, wire, linked_metadata
):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    old = profile(wire, linked_metadata)
    database = Database(old)
    # The corrected position lies in this chunk's tile (80, 10); the stored one was in (70, 10).
    wire["geolocation"]["coordinates"] = [80, 10]
    wire["source"][0]["date_updated"] = "2025-02-01T00:00:00Z"
    moved = profile(wire, linked_metadata)
    old_slot, new_slot = owner_slot(old), owner_slot(moved)
    repository = FakeRepository(database, counts={old_slot: (1, 0)}, west=80)
    processor, store = processor_for(tmp_path, repository, [wire], linked_metadata)
    processor.publish()
    by_slot = {generation["logical_key"]: generation for generation in repository.generations}
    assert set(by_slot) == {old_slot, new_slot}
    assert by_slot[old_slot]["membership_manifest"] == [] and "object_key" not in by_slot[old_slot]
    assert by_slot[new_slot]["kind"] == "part" and len(store.data) == 1
    # The old slot loses its only profile and gains none: its receipt proves the empty domain,
    # which needs the stored count. The new slot is filled inside the selection: no count.
    (read,) = [call for call in repository.calls if isinstance(call, tuple)]
    assert read[2] == (old_slot,)
    receipts = {receipt["logical_key"]: receipt for receipt in repository.receipts}
    assert set(receipts) == {old_slot, new_slot}
    assert receipts[old_slot]["stored_disposition"] == "empty_stored_domain"
    assert receipts[new_slot]["stored_disposition"] == "active_generation"
    assert "base_version" not in receipts[old_slot]  # it is a changed slot: generation base


def test_P09b_replay_of_stored_profiles_publishes_nothing_and_counts_the_own_slot(
    tmp_path, wire, linked_metadata
):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    value = profile(wire, linked_metadata)
    slot = owner_slot(value)
    repository = FakeRepository(Database(value), counts={slot: (5, 2)})
    processor, store = processor_for(tmp_path, repository, [wire], linked_metadata)
    assert processor.process() == "complete"
    assert repository.generations == [] and store.data == {}
    assert repository.levels == [] and len(repository.staged) == 1
    (receipt,) = repository.receipts
    assert receipt["logical_key"] == slot and receipt["base_version"] == 4
    assert (receipt["fetch_disposition"], receipt["stored_disposition"]) == (
        "profiles_returned",
        "active_generation",
    )
    assert receipt["evidence"]["selected_profiles"] == 2


def test_P09a_empty_fetch_over_retained_science_is_source_absence(tmp_path, linked_metadata):
    value_slot = "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2"
    repository = FakeRepository(Database(), counts={value_slot: (3, 1)})
    processor, store = processor_for(tmp_path, repository, [], linked_metadata)
    processor.publish()
    (receipt,) = repository.receipts
    assert (receipt["fetch_disposition"], receipt["stored_disposition"]) == (
        "source_absence_over_retained",
        "active_generation",
    )
    empty = FakeRepository(Database(), counts={value_slot: (0, 0)})
    processor, _ = processor_for(tmp_path, empty, [], linked_metadata)
    processor.publish()
    assert (empty.receipts[0]["fetch_disposition"], empty.receipts[0]["stored_disposition"]) == (
        "verified_empty_fetch",
        "empty_stored_selection",
    )


class FakeCopy:
    def __init__(self, sql):
        self.sql, self.types, self.rows = sql, None, []

    def set_types(self, types):
        self.types = types

    def write_row(self, row):
        self.rows.append(tuple(row))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeCursor:
    def __init__(self, rows=()):
        self.rows, self.executed, self.copies = list(rows), [], []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def copy(self, sql):
        self.copies.append(FakeCopy(sql))
        return self.copies[-1]


def repository_over(cursor):
    repository = Repository.__new__(Repository)

    @contextmanager
    def transaction(**kwargs):
        yield cursor

    repository.transaction = transaction
    return repository


def stored_row(value, identifier):
    return {
        "id": identifier,
        "source_profile_id": value.source_profile_id,
        "cycle_number": value.cycle,
        "direction": value.direction,
        "fallback_complete": value.cycle is not None and value.direction in ("A", "D"),
        "identity_observed_at": timestamp(value.observed_at),
        "observation_segment": "single",
        "platform_number": value.platform,
    }


def test_P01_identities_batch_assigns_each_profile_only_its_own_matches(wire, linked_metadata):
    wire["profile_direction"] = "A"
    first = profile(wire, linked_metadata)
    wire["_id"], wire["cycle_number"] = "other-id", wire["cycle_number"] + 1
    second = profile(wire, linked_metadata)
    wire["_id"], wire["cycle_number"] = "unrelated-id", wire["cycle_number"] + 5
    unrelated = profile(wire, linked_metadata)
    ids = [uuid.UUID(int=index + 1) for index in range(3)]
    # The rows the one query would return: a stable-id match, a natural-key match for the
    # second profile (no stable id stored), and a row of a profile not in the chunk.
    alias_less = replace(second, source_profile_id=None)
    rows = [
        stored_row(first, ids[0]),
        stored_row(alias_less, ids[1]),
        stored_row(replace(unrelated, platform="9999999", source_profile_id="elsewhere"), ids[2]),
    ]
    cursor = FakeCursor(rows)
    found = repository_over(cursor).identities_batch([first, second])
    assert [row.id for row in found[first.identity]] == [ids[0]]
    assert [row.id for row in found[second.identity]] == [ids[1]]
    ((sql, params),) = cursor.executed
    assert "unnest" in sql and params[0] == sorted(
        {first.source_profile_id, second.source_profile_id}
    )
    assert params[1:] == (
        [first.platform, first.platform],
        [first.cycle, second.cycle],
        ["A", "A"],
    )
    assert repository_over(FakeCursor()).identities_batch([]) == {}


def test_P06_stage_levels_streams_typed_rows_in_binary(wire, linked_metadata):
    first = profile(wire, linked_metadata)
    wire["_id"], wire["cycle_number"] = "second-staged", wire["cycle_number"] + 1
    second = profile(wire, linked_metadata)
    cursor = FakeCursor()
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 3)
    tables = (staging_table(first, 0), staging_table(second, 1))
    repository_over(cursor).stage_levels(authority, tables)
    (copy,) = cursor.copies
    assert copy.sql.endswith("FROM STDIN WITH (FORMAT BINARY)")
    assert copy.types[:5] == ["uuid", "uuid", "int8", "int4", "int4"] and len(copy.types) == 41
    assert len(copy.rows) == 6 and all(len(row) == 41 for row in copy.rows)
    assert copy.rows[0][:5] == (authority.run, authority.chunk, 3, 0, 0)
    assert copy.rows[5][:5] == (authority.run, authority.chunk, 3, 1, 2)
    columns = [name for name, _ in MEASUREMENT_COLUMNS]
    assert dict(zip(columns, copy.rows[1][5:], strict=True)) == {
        name: first.levels[1][name] for name in columns
    }
    # A single table and a lone-table iterable stage the same rows; a short table is refused.
    again = FakeCursor()
    repository_over(again).stage_levels(authority, staging_table(first, 0))
    assert [row[3:] for row in again.copies[0].rows] == [row[3:] for row in copy.rows[:3]]
    with pytest.raises(Rejection, match="invalid_level_table"):
        repository_over(FakeCursor()).stage_levels(
            authority, pa.table({"occurrence_index": [0], "level_index": [0]})
        )


def test_P06_stage_candidates_clears_then_copies_slim_rows(wire, linked_metadata):
    value = profile(wire, linked_metadata)
    cursor = FakeCursor()
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 3)
    row = {"occurrence_index": 4, **staged_candidate(value, uuid.uuid4(), uuid.uuid4())}
    repository_over(cursor).stage_candidates(authority, [row])
    assert cursor.executed[0][0] == "SELECT app.clear_staging(%s,%s,%s,%s)"
    (copy,) = cursor.copies
    ((run, chunk, fence, occurrence, data),) = copy.rows
    assert (run, chunk, fence, occurrence) == (authority.run, authority.chunk, 3, 4)
    assert json.loads(data)["level_count"] == 3 and "levels" not in json.loads(data)
    with pytest.raises(Rejection, match="profile_count_limit"):
        repository_over(FakeCursor()).stage_candidates(authority, [row] * 2001)
    with pytest.raises(Rejection, match="invalid_occurrence_index"):
        repository_over(FakeCursor()).stage_candidates(
            authority, [{**row, "occurrence_index": 2000}]
        )


def test_P08_compactable_slots_lists_slots_with_several_parts():
    cursor = FakeCursor([{"logical_key": "a"}, {"logical_key": "b"}])
    environment = uuid.uuid4()
    assert repository_over(cursor).compactable_slots(environment) == ["a", "b"]
    ((sql, params),) = cursor.executed
    assert "kind='part'" in sql and "HAVING count(*)>=%s" in sql and params == (environment, 2)


class ScriptedCursor(FakeCursor):
    """Answers the first executes in order, then only records (the compact_slot call)."""

    def __init__(self, *results):
        super().__init__()
        self.script, self.current = list(results), []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        self.current = self.script.pop(0) if self.script else []

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return list(self.current)


def stored_parts(tmp_path, wire, linked_metadata):
    """Two published parts (B is replaced by the second) and the manifest of their slot."""
    ids = [uuid.UUID(int=index + 1) for index in range(3)]
    values = []
    for number in range(3):
        wire["_id"], wire["cycle_number"] = f"compact-{number}", 400 + number
        values.append(profile(wire, linked_metadata))
    replaced_wire = copy.deepcopy(wire)
    replaced_wire["_id"], replaced_wire["cycle_number"] = "compact-1", 401
    replaced_wire["data"][0][0] += 1
    replaced = profile(replaced_wire, linked_metadata)
    store, objects = ObjectsStore(), []
    for name, entries in (
        ("one", [(ids[0], values[0]), (ids[1], values[1])]),
        ("two", [(ids[1], replaced), (ids[2], values[2])]),
    ):
        path = tmp_path / (name + ".parquet")
        write_snapshot(path, sorted(entries), deadline=time.monotonic() + 30)
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        key = f"normalised/sha256/{digest}.parquet"
        store.data[key] = payload
        objects.append(
            {
                "id": uuid.uuid4(),
                "kind": "part",
                "object_key": key,
                "sha256": digest,
                "bytes": len(payload),
            }
        )
    manifest = [
        {"profile_id": str(ids[0]), "hash": values[0].content_hash, "levels": 3},
        {"profile_id": str(ids[1]), "hash": replaced.content_hash, "levels": 3},
        {"profile_id": str(ids[2]), "hash": values[2].content_hash, "levels": 3},
    ]
    return store, objects, manifest, ids


def test_P08_compact_builds_one_snapshot_from_the_parts_and_swaps_it_in_one_call(
    tmp_path, wire, linked_metadata
):
    store, objects, manifest, ids = stored_parts(tmp_path, wire, linked_metadata)
    environment, slot = uuid.uuid4(), "argovis/core/2025-01/70:10/slot"
    cursor = ScriptedCursor([{"slot_version": 2, "membership_manifest": manifest}], objects)
    outcome = repository_over(cursor).compact(environment, slot, store, time.monotonic() + 60)
    assert outcome == "compacted"
    sql, params = cursor.executed[-1]
    assert sql == "SELECT app.compact_slot(%s,%s,%s)" and params[:2] == (environment, slot)
    generation = params[2].obj
    json.dumps(generation)  # plain JSON: no certificate object, no Arrow objects
    assert generation["kind"] == "snapshot" and generation["base_version"] == 2
    assert generation["membership_manifest"] == manifest
    assert generation["supersedes"] == [str(item["id"]) for item in objects]
    assert (generation["profile_count"], generation["row_count"]) == (3, 9)
    snapshot = store.data[generation["object_key"]]
    assert hashlib.sha256(snapshot).hexdigest() == generation["sha256"]
    assert generation["bytes"] == len(snapshot)
    table = pq.read_table(io.BytesIO(snapshot))
    assert table.num_rows == 9 and sorted(set(table["profile_id"].to_pylist())) == [
        str(identifier) for identifier in ids
    ]
    assert generation["verification_evidence"]["rows"] == 9


def test_P08_compact_with_nothing_to_merge_or_an_emptied_slot(tmp_path, wire, linked_metadata):
    store, objects, manifest, ids = stored_parts(tmp_path, wire, linked_metadata)
    environment, slot = uuid.uuid4(), "argovis/core/2025-01/70:10/slot"
    snapshots_only = [{**objects[0], "kind": "snapshot"}]
    cursor = ScriptedCursor([{"slot_version": 2, "membership_manifest": manifest}], snapshots_only)
    assert repository_over(cursor).compact(environment, slot, store, time.monotonic() + 60) == (
        "unchanged"
    )
    assert len(cursor.executed) == 2  # reads only
    # Every profile moved away: the parts are superseded and no snapshot object is written.
    cursor = ScriptedCursor([{"slot_version": 3, "membership_manifest": []}], objects)
    before = len(store.data)
    assert repository_over(cursor).compact(environment, slot, store, time.monotonic() + 60) == (
        "compacted"
    )
    generation = cursor.executed[-1][1][2].obj
    assert generation["membership_manifest"] == [] and "object_key" not in generation
    assert len(generation["supersedes"]) == 2 and len(store.data) == before
    # A part whose bytes changed under its recorded digest is never merged.
    tampered = [{**objects[0], "sha256": "0" * 64}, objects[1]]
    cursor = ScriptedCursor([{"slot_version": 2, "membership_manifest": manifest}], tampered)
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        repository_over(cursor).compact(environment, slot, store, time.monotonic() + 60)


def test_D_queue_calls_pass_the_ticket_kind_and_extend_unstarted_leases():
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 2, 5)
    identifier = uuid.uuid4()
    cursor = ScriptedCursor()
    cursor.fetchone = lambda: {"id": identifier, "n": 3}
    repository = repository_over(cursor)
    assert repository.ticket(authority) == identifier
    assert repository.ticket(authority, "acquire") == identifier
    assert cursor.executed[0][1] == (*authority.arguments, "process")
    assert cursor.executed[1][1] == (*authority.arguments, "acquire")
    assert repository.extend_unstarted_leases(authority.run, 2) == 3
    assert cursor.executed[2][1] == (authority.run, 2)


def test_I02_chunk_internal_natural_alias_conflict(wire, linked_metadata):
    """Re-homed from test_parquet.py (it used the removed workflow.preview)."""
    document = decode_json(json.dumps(wire).encode())
    first = map_profile(document, linked_metadata, CanonicalBudget())
    document["_id"] = "different-id"
    second = map_profile(document, linked_metadata, CanonicalBudget())
    # Complete fallback identity agrees but two stable IDs cannot become two inserts.
    if first.direction == "U":
        document["profile_direction"] = "A"
        document["_id"] = first.source_profile_id
        first = map_profile(document, linked_metadata, CanonicalBudget())
        document["_id"] = "different-id"
        second = map_profile(document, linked_metadata, CanonicalBudget())
    with ProfileSpool() as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(second, uuid.uuid4(), 1)
        with pytest.raises(Rejection, match="identity_conflict"):
            Database().prepare(spool)


def test_every_exception_category_of_the_publication_migrations_is_a_safe_category():
    raised = set()
    for name in ("0012_work_queue.sql", "0013_publication_v4.sql"):
        text = (ROOT / "infra/migrations/versions" / name).read_text()
        raised |= set(re.findall(r"RAISE EXCEPTION '([a-z_0-9]+)'", text))
    assert raised and not raised - SAFE_DATABASE_CATEGORIES
