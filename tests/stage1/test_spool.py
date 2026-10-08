import copy
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.identity import StoredIdentity
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import write_snapshot
from floatchat_core.ingestion.planning import Interval, RunPolicy, timestamp
from floatchat_core.ingestion.spool import ProfileSpool
from floatchat_core.ingestion.workflow import StoredScience, owner_slot


def profile(wire, metadata):
    return map_profile(decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget())


def stored(value):
    identifier = uuid.uuid4()
    return StoredScience(
        StoredIdentity(
            identifier,
            value.platform,
            value.source_profile_id,
            value.cycle,
            value.direction,
            value.natural_key,
        ),
        value,
    )


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


def test_N08_spool_reuses_certified_bytes_without_new_conversion_and_detects_corruption(
    tmp_path, wire, linked_metadata
):
    value = profile(wire, linked_metadata)
    conversions = []

    @contextmanager
    def counted():
        budget = CanonicalBudget()
        yield budget
        conversions.append(budget.run_used)

    with ProfileSpool(tmp_path / "cached.sqlite", budget_factory=counted) as spool:
        arguments = (value.canonical_bytes, value.content_hash, value.source_profile_id, "null")
        assert spool.restore(*arguments).canonical_bytes == value.canonical_bytes
        assert conversions == [len(value.canonical_bytes)]
        assert spool.restore(*arguments).content_hash == value.content_hash
        assert conversions == [len(value.canonical_bytes)]
        with pytest.raises(Rejection, match="stored_scientific_hash_mismatch"):
            spool.restore(value.canonical_bytes + b" ", *arguments[1:])
        assert conversions == [len(value.canonical_bytes)]
    # A new process/spool must certify again; no persistent budget reset or
    # transferable cache receipt is inferred from the prior spool's check.
    with ProfileSpool(tmp_path / "recovery.sqlite", budget_factory=counted) as spool:
        spool.restore(*arguments)
    assert conversions == [len(value.canonical_bytes)] * 2


def test_T06_F02_spilled_snapshot_preserves_older_retained_observations(
    tmp_path, wire, linked_metadata
):
    retained_wire = copy.deepcopy(wire)
    retained_wire["timestamp"] = "2025-10-01T00:00:00Z"
    retained_wire["_id"] = "retained-old"
    old = stored(profile(retained_wire, linked_metadata))
    wire["timestamp"] = "2025-10-07T00:00:00Z"
    eligible = stored(profile(wire, linked_metadata))
    initial = RunPolicy.capture(
        "normal", "synthetic-env", actual_now=timestamp("2026-10-01T00:00:00Z")
    )
    advanced = RunPolicy.capture(
        "normal", "synthetic-env", actual_now=timestamp("2026-10-06T00:00:00Z")
    )
    selection = Interval(timestamp("2025-10-06T00:00:00Z"), timestamp("2025-11-01T00:00:00Z"))
    advanced.validate(selection)
    assert initial.eligible.contains(timestamp(old.profile.observed_at))
    assert not advanced.eligible.contains(timestamp(old.profile.observed_at))
    assert advanced.eligible.contains(timestamp(eligible.profile.observed_at))
    corrected_wire = copy.deepcopy(wire)
    corrected_wire["data"][0][0] += 1
    corrected_wire["data"] = [array[:2] for array in corrected_wire["data"]]
    corrected = newer(profile(corrected_wire, linked_metadata))
    with ProfileSpool(tmp_path / "science.sqlite") as spool:
        spool.add(corrected, uuid.uuid4(), 0)
        spool.prepare(lambda candidate: (eligible,))
        spool.retain(iter((old, eligible)))
        slot = owner_slot(corrected)
        members = spool.membership(slot)
        assert {row["profile_id"] for row in members} == {
            str(old.identity.id),
            str(eligible.identity.id),
        }
        old_member = next(row for row in members if row["profile_id"] == str(old.identity.id))
        assert old_member["hash"] == old.profile.content_hash
        evidence = write_snapshot(
            tmp_path / "snapshot.parquet", spool.profiles(slot), deadline=time.monotonic() + 20
        )
        assert evidence["profiles"] == 2 and evidence["rows"] == 5
        eligible_members = [
            (identifier, value)
            for identifier, value in spool.profiles(slot)
            if advanced.eligible.contains(timestamp(value.observed_at))
            and selection.contains(timestamp(value.observed_at))
        ]
        assert [identifier for identifier, _ in eligible_members] == [eligible.identity.id]
        assert sum(len(value.levels) for _, value in eligible_members) == 2
        assert sum(row["levels"] for row in members) == evidence["rows"]
        assert len(corrected.levels) - len(eligible.profile.levels) == -1
        assert spool.outcomes[0][2] == "newer"


def test_P09c_spilled_ownership_correction_leaves_empty_old_slot(tmp_path, wire, linked_metadata):
    old = stored(profile(wire, linked_metadata))
    wire["geolocation"]["coordinates"] = [80, 10]
    corrected = newer(profile(wire, linked_metadata))
    with ProfileSpool(tmp_path / "science.sqlite") as spool:
        spool.add(corrected, uuid.uuid4(), 0)
        spool.prepare(lambda candidate: (old,))
        spool.retain((old,))
        assert spool.membership(owner_slot(old.profile)) == []
        assert spool.membership(owner_slot(corrected))[0]["profile_id"] == str(old.identity.id)


def test_F02_duplicate_occurrences_keep_indices_and_do_not_duplicate_science(
    tmp_path, wire, linked_metadata
):
    first = profile(wire, linked_metadata)
    wire["_id"] = "second-profile"
    wire["cycle_number"] += 1
    second = profile(wire, linked_metadata)
    with ProfileSpool(tmp_path / "science.sqlite") as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(first, uuid.uuid4(), 1)
        spool.add(second, uuid.uuid4(), 2)
        spool.prepare(lambda candidate: ())
        spool.retain(())
        candidates = list(spool.candidates())
        assert [row["occurrence_index"] for row in candidates] == [0, 2]
        assert len(spool.membership(owner_slot(first))) == 2
        assert spool.outcomes[0] == (1, first.identity, "identical_duplicate", 3)


def test_B08_private_spool_never_overwrites_existing_file(tmp_path):
    path = tmp_path / "already.sqlite"
    path.write_bytes(b"preserved")
    with pytest.raises(Rejection, match="invalid_private_spool"):
        ProfileSpool(path)
    assert path.read_bytes() == b"preserved"


def test_B01_N08_spool_canonical_limit_checked_before_disk_insertion(
    tmp_path, wire, linked_metadata
):
    value = profile(wire, linked_metadata)
    with ProfileSpool(tmp_path / "science.sqlite") as spool:
        spool.incoming_bytes = 256 * 1024**2
        with pytest.raises(Rejection, match="chunk_scientific_resource_limit"):
            spool.add(value, uuid.uuid4(), 0)
        assert spool.connection.execute("SELECT count(*) FROM incoming").fetchone()[0] == 0


def test_I03_spool_rejects_two_stable_ids_for_one_natural_identity(tmp_path, wire, linked_metadata):
    wire["profile_direction"] = "A"
    first = profile(wire, linked_metadata)
    wire["_id"] = "different-stable-id"
    second = profile(wire, linked_metadata)
    with ProfileSpool(tmp_path / "science.sqlite") as spool:
        spool.add(first, uuid.uuid4(), 0)
        spool.add(second, uuid.uuid4(), 1)
        with pytest.raises(Rejection, match="identity_conflict"):
            spool.prepare(lambda candidate: ())
