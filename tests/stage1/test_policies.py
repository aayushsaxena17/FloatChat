import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from floatchat_core.ingestion.argovis import map_profile, request_parameters, verify_inventory
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.planning import (
    ACCEPTANCE_REFERENCE,
    GEOMETRY_SHA256,
    Interval,
    PlannedChunk,
    RunPolicy,
    Tile,
    in_region,
    month_interval,
    month_start,
    plan,
    shift_months,
    split,
    timestamp,
)
from floatchat_core.ingestion.revisions import Revision, compare
from floatchat_core.ingestion.states import exit_code, reduce_run, schedule_interval, transition


def mapped(wire, linked_metadata):
    return map_profile(decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget())


def test_T01_T03_immutable_time_month_window():
    policy = RunPolicy.capture("normal", "test", actual_now=datetime(2024, 2, 29, 3, tzinfo=UTC))
    assert policy.eligible.start == datetime(2023, 2, 28, 3, tzinfo=UTC)
    assert policy.eligible.contains(policy.eligible.start)
    assert not policy.eligible.contains(policy.reference)
    assert shift_months(datetime(2025, 3, 31, tzinfo=UTC), -1).day == 28
    with pytest.raises(Rejection, match="outside_rolling_window"):
        policy.validate(month_interval("2025-01", "2025-03"))
    acceptance = RunPolicy.capture("acceptance", "test", acceptance_marker=True)
    acceptance.validate(month_interval("2025-01", "2025-03"))
    assert acceptance.reference == ACCEPTANCE_REFERENCE
    assert month_interval("2025-01", "2025-03").end == ACCEPTANCE_REFERENCE


def test_T04_acceptance_marker_required():
    with pytest.raises(Rejection, match="acceptance_environment_required"):
        RunPolicy.capture("acceptance", "production")


def test_T05_plan_and_adaptive_split_cover():
    interval = month_interval("2025-01", "2025-03")
    chunks = plan(interval)
    tile_chunks = [c for c in chunks if c.tile == Tile(20, -60)]
    assert tile_chunks[0].interval.start == interval.start
    assert tile_chunks[-1].interval.end == interval.end
    assert all(
        a.interval.end == b.interval.start
        for a, b in zip(tile_chunks, tile_chunks[1:], strict=False)
    )
    # Plan v2 (ADR-0041): one whole UTC calendar month per tile, 3 x 90 = 270 roots.
    assert len(chunks) == 270
    assert [c.interval for c in tile_chunks] == [
        Interval(month_start(c.interval.start), shift_months(month_start(c.interval.start), 1))
        for c in tile_chunks
    ]
    assert all(
        c.interval.start.month == (c.interval.end - timedelta(microseconds=1)).month for c in chunks
    )
    # A partial request is clipped to its own bounds, still never crossing a month.
    partial = plan(Interval(datetime(2025, 1, 20, tzinfo=UTC), datetime(2025, 2, 3, tzinfo=UTC)))
    days = sorted({(c.interval.start.day, c.interval.end.day) for c in partial})
    assert days == [(1, 3), (20, 1)]
    left, right = split(tile_chunks[0])
    assert left.interval.start == interval.start
    assert (
        left.interval.end == right.interval.start
        and right.interval.end == tile_chunks[0].interval.end
    )
    with pytest.raises(Rejection, match="chunk_count_limit"):
        plan(interval, max_chunks=1)
    with pytest.raises(Rejection, match="minimum_chunk_exceeded"):
        split(
            PlannedChunk(
                Interval(interval.start, interval.start + timedelta(hours=1)), Tile(20, -60, 1, 1)
            )
        )


@pytest.mark.parametrize(
    "lon,lat,inside",
    [(20, -60, True), (120, 30, True), (70, 10, True), (19, 10, False), (70, 31, False)],
)
def test_G01_region(lon, lat, inside):
    assert in_region(Decimal(lon), Decimal(lat)) == inside
    assert len(GEOMETRY_SHA256) == 64


@pytest.mark.parametrize("lon,lat", [(181, 0), (0, 91), ("NaN", 0), (0, "Infinity")])
def test_G01_invalid_coordinates(lon, lat):
    with pytest.raises(Rejection, match="invalid_coordinates"):
        in_region(Decimal(lon), Decimal(lat))


def test_G02_unique_tile_ownership():
    for longitude, latitude in [(30, -50), (120, 30), (20, -60), (70, 10)]:
        owners = [
            c.tile
            for c in plan(month_interval("2025-01", "2025-01"))[:90]
            if c.tile.owns(Decimal(longitude), Decimal(latitude))
        ]
        assert len(owners) == 1
    a, b = Tile(20, -60), Tile(30, -60)
    assert json.loads(a.polygon())[1][0] > 30
    assert json.loads(b.polygon())[0][0] < 30


def test_G03_documented_request():
    chunk = plan(month_interval("2025-01", "2025-01"))[0]
    parameters = request_parameters(chunk, inventory=False)
    assert set(parameters) == {"startDate", "endDate", "polygon", "data"}
    assert parameters["data"] == "all"
    polygon = json.loads(parameters["polygon"])
    assert polygon[0] == polygon[-1] and len(polygon) == 5
    assert "data" not in request_parameters(chunk, inventory=True)


def test_G04_G05_inventory_not_fake_empty(wire):
    document = decode_json(json.dumps(wire).encode())
    interval = month_interval("2025-01", "2025-01")
    verify_inventory([document], [document], [document], interval)
    verify_inventory([], [], [], interval)
    for bodies in [([document], [], [document]), ([], [document], []), ([], [], {})]:
        with pytest.raises(Rejection):
            verify_inventory(*bodies, interval)


def test_S01_modes_qc_units_and_absent_variant(wire, linked_metadata):
    for mode, field in [
        ("R", "temperature"),
        ("A", "temperature_adjusted"),
        ("D", "temperature_adjusted"),
    ]:
        wire["data_info"][2][0][1] = mode
        wire["data_info"][0].append("temperature_argoqc")
        wire["data_info"][2].append([None, None])
        wire["data"].append([1, 0, "unknown"])
        profile = mapped(wire, linked_metadata)
        assert profile.levels[0][field] == 28.669001
        other = "temperature_adjusted" if mode == "R" else "temperature"
        assert profile.levels[0][other] is None
        q = "temperature_qc" if mode == "R" else "temperature_adjusted_qc"
        assert profile.levels[0][q] == "1" and profile.levels[1][q] == "0"
        assert profile.levels[2][q] is None and profile.levels[2][q + "_source"] == "unknown"
        assert profile.levels[0]["salinity"] is None
        assert profile.levels[0]["temperature_error"] is None
        wire["data_info"][0].pop()
        wire["data_info"][2].pop()
        wire["data"].pop()


@pytest.mark.parametrize(
    "mutation,category",
    [
        ("short", "mismatched_array_lengths"),
        ("empty", "invalid_array_length"),
        ("duplicate_name", "invalid_data_info"),
        ("unknown_mode", "unknown_data_mode"),
        ("unknown_unit", "unknown_unit"),
        ("missing_metadata", "unresolved_metadata"),
        ("missing_direction_no_id", "invalid_direction"),
        ("unknown_field", "unsupported_profile_schema"),
        ("negative_cycle", "invalid_cycle"),
        ("string_numeric", "invalid_scientific_numeric_string"),
    ],
)
def test_I01_S03_S04_reject_entire_profile(wire, linked_metadata, mutation, category):
    if mutation == "short":
        wire["data"][0].pop()
    if mutation == "empty":
        wire["data"][0] = []
    if mutation == "duplicate_name":
        wire["data_info"][0][1] = "temperature"
    if mutation == "unknown_mode":
        wire["data_info"][2][0][1] = "X"
    if mutation == "unknown_unit":
        wire["data_info"][2][0][0] = "K"
    if mutation == "missing_metadata":
        wire["metadata"] = ["absent"]
    if mutation == "missing_direction_no_id":
        wire.pop("_id")
        wire.pop("profile_direction")
    if mutation == "unknown_field":
        wire["cursor"] = "next"
    if mutation == "negative_cycle":
        wire["cycle_number"] = -1
    if mutation == "string_numeric":
        wire["data"][0][0] = "1"
    with pytest.raises(Rejection, match=category):
        mapped(wire, linked_metadata)


def test_I02_R01_retrieval_and_format_not_scientific(wire, linked_metadata):
    original = mapped(wire, linked_metadata)
    wire["date_updated_argovis"] = "2026-01-01T00:00:00Z"
    wire["source"][0]["date_updated"] = "2026-01-01T00:00:00Z"
    wire["data"][1][0] = 2.0
    later = mapped(wire, linked_metadata)
    assert later.content_hash == original.content_hash
    assert later.identity == original.identity
    assert (
        compare(later.content_hash, later.revision, original.content_hash, original.revision)
        == "revision_only"
    )


def test_I01_I04_directions_fallback_pressure_indices(wire, linked_metadata):
    a = mapped(wire, linked_metadata)
    wire["profile_direction"] = "D"
    wire.pop("_id")
    wire["data"][1] = [2, 2, 1]
    b = mapped(wire, linked_metadata)
    assert a.natural_key != b.natural_key
    assert [x["level_index"] for x in b.levels] == [0, 1, 2]
    assert "repeated_pressure" in b.levels[1]["pressure_flags"]
    assert "nonmonotonic_pressure" in b.levels[2]["pressure_flags"]


@pytest.mark.parametrize(
    "incoming,stored,same,outcome",
    [
        (None, None, True, "noop"),
        (None, None, False, "revision_conflict"),
        ((1, 1), (1, 1), True, "noop"),
        ((1, 1), (1, 1), False, "revision_conflict"),
        ((2, 2), (1, 1), False, "newer"),
        ((2, 2), (1, 1), True, "revision_only"),
        ((1, 1), (2, 2), False, "stale_skip"),
        ((1, 1), (2, 2), True, "stale_skip"),
        ((2, 1), (1, 2), True, "unordered_noop"),
        ((2, 1), (1, 2), False, "revision_conflict"),
        ((1, 1), None, True, "unordered_noop"),
        ((1, 1), None, False, "revision_conflict"),
    ],
)
def test_R01_R06_revision_vectors(incoming, stored, same, outcome):
    def vector(dates):
        return (
            None
            if dates is None
            else Revision(
                "test",
                tuple(
                    (key, datetime(2025, 1, day, tzinfo=UTC))
                    for key, day in zip(("a", "b"), dates, strict=True)
                ),
            )
        )

    assert compare("a", vector(incoming), "a" if same else "b", vector(stored)) == outcome


@pytest.mark.parametrize(
    "states,result,code",
    [
        (["complete"], "complete", 0),
        (["complete", "quarantined"], "partial", 3),
        (["complete", "failed"], "partial", 3),
        (["quarantined"], "quarantined", 4),
        (["failed", "quarantined"], "failed", 5),
        (["failed"], "failed", 5),
    ],
)
def test_C02_aggregate_and_exit(states, result, code):
    assert reduce_run(states) == result and exit_code(result) == code
    assert exit_code(result, cancellation_affected=True) == 130


def test_C01_legal_late_quarantine_and_terminal():
    transition("publishing", "quarantined")
    with pytest.raises(Rejection):
        transition("complete", "fetching")
    with pytest.raises(Rejection):
        transition("planned", "complete")
    with pytest.raises(Rejection):
        reduce_run(["landed"])


def test_D03_overlap_bounded_catchup():
    now = datetime(2026, 10, 6, tzinfo=UTC)
    policy = RunPolicy.capture("normal", "test", actual_now=now)
    assert schedule_interval(policy, None) == Interval(now - timedelta(days=14), now)
    backlog = schedule_interval(policy, now - timedelta(days=90))
    assert backlog.start == now - timedelta(days=104)
    assert backlog.end - backlog.start == timedelta(days=31)
    with pytest.raises(Rejection):
        schedule_interval(RunPolicy.capture("acceptance", "test", acceptance_marker=True), None)


def test_T02_timestamp_precision_offsets():
    assert timestamp("2025-01-01T01:00:00+01:00") == datetime(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(Rejection):
        timestamp("2025-01-01T00:00:00")
    with pytest.raises(Rejection):
        timestamp("2025-01-01T00:00:00.1234567Z")


def test_B05_revision_url_sanitization(wire, linked_metadata):
    baseline = mapped(wire, linked_metadata)
    candidate = copy.deepcopy(wire)
    candidate["source"][0]["url"] = (
        candidate["source"][0]["url"].replace("ftp://", "ftp://sentinel@")
        + "?key=sentinel#sentinel"
    )
    sanitized = mapped(candidate, linked_metadata)
    assert sanitized.revision == baseline.revision
    assert b"sentinel" not in sanitized.canonical_bytes
