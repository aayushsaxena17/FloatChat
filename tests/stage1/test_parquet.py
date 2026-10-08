import json
import time
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import (
    schema,
    storage_comparison,
    verify_snapshot,
    write_snapshot,
)
from floatchat_core.ingestion.workflow import preview


def test_P03_F03_full_snapshot_scientific_verification(tmp_path, wire, linked_metadata):
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    identifier = uuid.uuid4()
    path = tmp_path / "snapshot.parquet"
    result = write_snapshot(path, {identifier: profile}, deadline=time.monotonic() + 10)
    assert result["profiles"] == 1
    assert result["rows"] == len(profile.levels)
    assert {
        key: result[key] for key in verify_snapshot(path, deadline=time.monotonic() + 10)
    } == verify_snapshot(path, deadline=time.monotonic() + 10)
    table = pq.read_table(path)
    assert table.schema.equals(schema(), check_metadata=True)
    assert "revision" not in table.column_names
    assert "retrieved_at" not in table.column_names
    assert table["profile_hash"].to_pylist() == [profile.content_hash] * len(profile.levels)
    measured = result["storage_comparison"]
    # The comparison frame uses IPC from_pylist batches. Parquet decoding may
    # allocate redundant validity bitmaps even on entirely nonnull columns.
    equivalent = pa.Table.from_pylist(table.to_pylist(), schema=schema())
    assert equivalent.equals(table)
    frame = equivalent.to_pandas(types_mapper=pd.ArrowDtype)
    assert measured["pandas_deep_memory_bytes"] == int(
        frame.memory_usage(index=True, deep=True).sum()
    )
    assert measured["columns"] == table.column_names
    assert measured["parquet_bytes"] == path.stat().st_size
    assert measured["index"] == "RangeIndex"
    assert result["writer_options"]["compression_level"] == 3


def test_F06_repeatable_whole_frame_measurement_and_empty_ratio(tmp_path, wire, linked_metadata):
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    identifier = uuid.uuid4()
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    one = write_snapshot(first, {identifier: profile}, deadline=time.monotonic() + 10)
    two = write_snapshot(second, {identifier: profile}, deadline=time.monotonic() + 10)
    assert one == two and first.read_bytes() == second.read_bytes()
    assert one["storage_comparison"]["ratio_status"] == "measured"
    empty = storage_comparison(pa.Table.from_batches([], schema=schema()), 0)
    assert empty["ratio_status"] == "not-applicable" and empty["pandas_to_parquet_ratio"] is None


@pytest.mark.parametrize(
    "field,value,category",
    [
        ("pressure", 999.0, "snapshot_numeric_mismatch"),
        ("profile_hash", "a" * 64, "snapshot_scientific_hash_mismatch"),
        ("level_index", 5, "snapshot_profile_inconsistency"),
        ("temperature_qc", "9", "snapshot_level_mismatch"),
    ],
)
def test_P03_corrupted_science_rejected(tmp_path, wire, linked_metadata, field, value, category):
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    path = tmp_path / "snapshot.parquet"
    write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    rows = pq.read_table(path).to_pylist()
    for row in rows:
        row[field] = value
    pq.write_table(pa.Table.from_pylist(rows, schema=schema()), path)
    with pytest.raises(Rejection, match=category):
        verify_snapshot(path, deadline=time.monotonic() + 10)


def test_I02_chunk_internal_natural_alias_conflict(wire, linked_metadata):
    wire_profile = decode_json(json.dumps(wire).encode())
    metadata = linked_metadata
    first = map_profile(wire_profile, metadata, CanonicalBudget())
    wire_profile["_id"] = "different-id"
    second = map_profile(wire_profile, metadata, CanonicalBudget())
    # Complete fallback identity agrees but two stable IDs cannot become two inserts.
    if first.direction == "U":
        wire_profile["profile_direction"] = "A"
        wire_profile["_id"] = first.source_profile_id
        first = map_profile(wire_profile, metadata, CanonicalBudget())
        wire_profile["_id"] = "different-id"
        second = map_profile(wire_profile, metadata, CanonicalBudget())
    with pytest.raises(Rejection, match="identity_conflict"):
        preview(((first, uuid.uuid4()), (second, uuid.uuid4())), ())
