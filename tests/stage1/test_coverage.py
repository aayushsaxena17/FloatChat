import hashlib
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from floatchat_core.ingestion.coverage import Receipt, covers, resolve
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.objects import (
    CatalogueRecord,
    CatalogueSnapshot,
    select_active_partitions,
)
from floatchat_core.ingestion.planning import Interval, Tile

TILE = Tile(70, 10)
START = datetime(2025, 1, 1, tzinfo=UTC)
END = START + timedelta(days=6)
INTERVAL = Interval(START, END)
SLOT = "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2"


def receipt(interval=INTERVAL, tile=TILE, *, version=0, empty=True, absence=False):
    return Receipt(
        uuid.uuid4(),
        interval,
        tile,
        SLOT,
        version,
        "source_absence_over_retained"
        if absence
        else "verified_empty_fetch"
        if empty
        else "profiles_returned",
        "empty_stored_selection" if empty else "active_generation",
        START.isoformat(),
    )


def test_G03_P01_split_space_time_union_and_missing_child_gap():
    mid = START + timedelta(days=3)
    pieces = tuple(
        receipt(interval, tile)
        for interval in (Interval(START, mid), Interval(mid, END))
        for tile in (Tile(70, 10, 5, 10), Tile(75, 10, 5, 10))
    )
    assert covers(INTERVAL, TILE, pieces, deadline=time.monotonic() + 1)
    assert not covers(INTERVAL, TILE, pieces[:-1], deadline=time.monotonic() + 1)
    assert covers(INTERVAL, TILE, pieces + pieces, deadline=time.monotonic() + 1)


def test_P09a_verified_empty_selection_has_receipts_no_gap():
    result = resolve(
        INTERVAL,
        (),
        {SLOT: 0},
        (receipt(),),
        lambda interval, slot: 0,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert not result.records and not result.gaps
    assert len(result.empty_evidence) == 1 and not result.source_absence_evidence


def test_P09b_retained_generation_and_source_absence_annotation():
    environment = uuid.uuid4()
    record = CatalogueRecord(
        uuid.uuid4(),
        environment,
        SLOT,
        1,
        1,
        "active",
        True,
        True,
        "indian-ocean-v1",
        "core-parquet-v1",
        "normalised/sha256/" + "a" * 64 + ".parquet",
        "a" * 64,
        50,
    )
    result = resolve(
        INTERVAL,
        (record,),
        {SLOT: 1},
        (receipt(version=1, empty=False, absence=True),),
        lambda interval, slot: 1,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert result.records == (record,) and not result.gaps
    assert not result.empty_evidence and len(result.source_absence_evidence) == 1


def test_P09c_prior_receipts_prove_fetch_but_old_empty_cannot_hide_new_membership():
    old = receipt(version=0)
    result = resolve(
        INTERVAL,
        (),
        {SLOT: 1},
        (old,),
        lambda interval, slot: 0,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert result.gaps == (SLOT + ":stored_empty_not_verified",)
    assert not result.empty_evidence


def test_P01_month_slot_never_manufactures_time_coverage():
    short = receipt(Interval(START, START + timedelta(hours=1)))
    result = resolve(
        INTERVAL,
        (),
        {SLOT: 0},
        (short,),
        lambda interval, slot: 0,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert SLOT + ":fetch_coverage" in result.gaps
    assert SLOT + ":stored_empty_not_verified" in result.gaps


def test_P09c_corrected_empty_domain_proof_and_historical_fetch_are_separate():
    previous = receipt(version=1, empty=False)
    correction = Receipt(
        uuid.uuid4(),
        Interval(START, START + timedelta(hours=1)),
        Tile(80, 10),
        SLOT,
        2,
        "profiles_returned",
        "empty_stored_domain",
        START.isoformat(),
    )
    result = resolve(
        INTERVAL,
        (),
        {SLOT: 2},
        (previous, correction),
        lambda interval, slot: 0,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert not result.records and not result.gaps
    assert result.empty_evidence == (f"{correction.identifier}@{correction.committed_at}",)


def stored_object(payload, *, kind, generation, environment, version=2):
    digest = hashlib.sha256(payload).hexdigest()
    return CatalogueRecord(
        uuid.uuid4(),
        environment,
        SLOT,
        generation,
        version,
        "active",
        True,
        True,
        "indian-ocean-v1",
        "core-parquet-v1",
        f"normalised/sha256/{digest}.parquet",
        digest,
        len(payload),
        kind,
        generation,
    )


def test_P08_a_slot_with_a_snapshot_and_later_parts_selects_every_object():
    environment = uuid.uuid4()
    snapshot = stored_object(b"snapshot", kind="snapshot", generation=3, environment=environment)
    part = stored_object(b"part-4", kind="part", generation=4, environment=environment)
    later = stored_object(b"part-5", kind="part", generation=5, environment=environment)
    result = resolve(
        INTERVAL,
        (snapshot, part, later),
        {SLOT: 2},
        (receipt(version=2, empty=False),),
        lambda interval, slot: 7,
        tiles=(TILE,),
        deadline=time.monotonic() + 1,
    )
    assert result.records == (snapshot, part, later) and not result.gaps
    with pytest.raises(Rejection, match="duplicate_active_catalogue_slot"):
        resolve(
            INTERVAL,
            (snapshot, replace(snapshot, partition_id=uuid.uuid4())),
            {SLOT: 2},
            (),
            lambda interval, slot: 1,
            tiles=(TILE,),
            deadline=time.monotonic() + 1,
        )
    with pytest.raises(Rejection, match="duplicate_active_catalogue_slot"):
        resolve(
            INTERVAL,
            (part, part),
            {SLOT: 2},
            (),
            lambda interval, slot: 1,
            tiles=(TILE,),
            deadline=time.monotonic() + 1,
        )


class Objects:
    def __init__(self, **objects):
        self.objects = objects

    def read(self, key, max_bytes, deadline):
        if key not in self.objects:
            raise Rejection("object_missing")
        return self.objects[key][:max_bytes]


def test_P08_selector_returns_parts_with_manifest_and_never_a_partial_slot():
    environment = uuid.uuid4()
    snapshot = stored_object(b"snapshot", kind="snapshot", generation=3, environment=environment)
    part = stored_object(b"part-4", kind="part", generation=4, environment=environment)
    manifest = [{"profile_id": str(uuid.uuid4()), "hash": "a" * 64, "levels": 3}]
    catalogue = CatalogueSnapshot(
        (snapshot, part), {SLOT: 2}, (), manifests={SLOT: manifest, "other": []}
    )
    store = Objects(**{snapshot.key: b"snapshot", part.key: b"part-4"})
    result = select_active_partitions(
        catalogue, store, environment, "indian-ocean-v1", "core-parquet-v1"
    )
    assert result.partitions == (snapshot, part) and not result.gaps
    assert result.manifests == {SLOT: manifest}
    # One unreadable part makes the whole slot a gap: no partial substitute is returned.
    store = Objects(**{snapshot.key: b"snapshot", part.key: b"corrupted"})
    result = select_active_partitions(
        catalogue, store, environment, "indian-ocean-v1", "core-parquet-v1"
    )
    assert not result.partitions and result.gaps == (SLOT + ":object_unavailable",)
    assert result.manifests == {}
    # The read budget covers all objects of the slot together.
    store = Objects(**{snapshot.key: b"snapshot", part.key: b"part-4"})
    result = select_active_partitions(
        catalogue, store, environment, "indian-ocean-v1", "core-parquet-v1", max_read_bytes=10
    )
    assert not result.partitions and result.gaps == (SLOT + ":verification_budget",)
    # Two snapshots in one slot are a corrupt catalogue.
    again = replace(snapshot, partition_id=uuid.uuid4())
    with pytest.raises(Rejection, match="duplicate_active_catalogue_slot"):
        select_active_partitions(
            CatalogueSnapshot((snapshot, again), {SLOT: 2}, ()),
            store,
            environment,
            "indian-ocean-v1",
            "core-parquet-v1",
        )
