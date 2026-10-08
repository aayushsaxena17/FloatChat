import time
import uuid
from datetime import UTC, datetime, timedelta

from floatchat_core.ingestion.coverage import Receipt, covers, resolve
from floatchat_core.ingestion.objects import CatalogueRecord
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
