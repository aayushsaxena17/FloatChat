import hashlib
import io
import json
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace as replace_field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from floatchat_core.ingestion import parquet
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import (
    WRITER_OPTIONS,
    PublicationSnapshotVerifier,
    schema,
    storage_comparison,
    verify_snapshot,
    write_snapshot,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from stage1_perf_profile import synthetic_chunk  # noqa: E402


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
    # Each result carries its own certificate object; the evidence around it is equal.
    certificates = one.pop("certificate"), two.pop("certificate")
    assert one == two and first.read_bytes() == second.read_bytes()
    assert certificates[0].digest == certificates[1].digest
    assert certificates[0].byte_count == certificates[1].byte_count == first.stat().st_size
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


def one_profile(wire, linked_metadata):
    return map_profile(decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget())


def synthetic_profiles(*shapes):
    """Profiles of different level counts with distinct identities, in identifier order."""
    profiles, offset = [], 0
    for count, levels in shapes:
        payload, _, metadata = synthetic_chunk(count, levels, offset=offset)
        meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
        profiles += [map_profile(d, meta, CanonicalBudget()) for d in documents(payload)]
        offset += count
    return [(uuid.UUID(int=index + 1), profile) for index, profile in enumerate(profiles)]


def v3_bytes(items):
    """What the stage1-v3 writer produced: rows() through from_pylist, one chunk per group."""
    rows = [row for identifier, profile in items for row in parquet.rows(identifier, profile)]
    sink = io.BytesIO()
    with pq.ParquetWriter(sink, schema(), **WRITER_OPTIONS) as writer:
        for start in range(0, len(rows), parquet.ROW_GROUP_ROWS):
            group = pa.Table.from_pylist(rows[start : start + parquet.ROW_GROUP_ROWS], schema())
            writer.write_table(group, row_group_size=parquet.ROW_GROUP_ROWS)
    return sink.getvalue()


def test_arrow_rows_equal_rows_oracle_and_file_bytes_equal_v3(tmp_path, monkeypatch):
    # Group edges and profile edges never line up, so the 64-row batches that decide
    # Parquet page cuts carry rows over from one profile (and group) to the next.
    monkeypatch.setattr(parquet, "ROW_GROUP_ROWS", 1000)
    items = synthetic_profiles((2, 699), (2, 211), (1, 1503), (2, 64), (1, 65), (1, 1))
    path = tmp_path / "snapshot.parquet"
    result = write_snapshot(path, items, deadline=time.monotonic() + 60)
    assert path.read_bytes() == v3_bytes(items)
    file = pq.ParquetFile(path)
    sizes = [file.metadata.row_group(index).num_rows for index in range(file.num_row_groups)]
    assert sizes == [1000, 1000, 1000, 1000, 1000, 1000][: len(sizes)] or sizes[-1] <= 1000
    assert sum(sizes) == result["rows"] == sum(len(profile.levels) for _, profile in items)
    assert len(sizes) > 3 and result["profiles"] == len(items)
    # The independent row-by-row path agrees with the Arrow one.
    audited = verify_snapshot(path, deadline=time.monotonic() + 60)
    assert {key: result[key] for key in audited} == audited


def test_hostile_text_in_header_and_levels_is_framed_exactly(tmp_path, wire, linked_metadata):
    hostile = ['},{"level_index":2,', '"],"longitude":{', "\\", 'é"\U0001f600', "}"]
    wire["vertical_sampling_scheme"] = '],"longitude":{"x":1},"levels":[{"level_index":'
    names, attributes, values = wire["data_info"]
    wire["data_info"] = [names + ["temperature_argoqc"], attributes, values + [[None, None]]]
    wire["data"] = wire["data"] + [hostile[:3]]
    profile = one_profile(wire, linked_metadata)
    path = tmp_path / "snapshot.parquet"
    items = [(uuid.UUID(int=1), profile)]
    result = write_snapshot(path, items, deadline=time.monotonic() + 10, audit=True)
    reference = pa.Table.from_pylist(list(parquet.rows(*items[0])), schema=schema())
    assert pq.read_table(path).equals(reference)
    assert path.read_bytes() == v3_bytes(items)
    assert result["certificate"].digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_header_is_cut_from_the_canonical_bytes_with_a_parsing_fallback(wire, linked_metadata):
    profile = one_profile(wire, linked_metadata)
    expected = next(parquet.rows(uuid.UUID(int=1), profile))["profile_content"]
    assert parquet._header(profile) == expected
    # Canonical bytes without the expected neighbouring key cannot be cut: parse instead.
    canonical = json.loads(profile.canonical_bytes)
    del canonical["longitude"]
    odd = replace_field(
        profile,
        canonical_bytes=json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(),
    )
    del canonical["levels"]
    assert parquet._header(odd) == json.dumps(canonical, sort_keys=True, separators=(",", ":"))


def test_evidence_keys_and_certificate(tmp_path, wire, linked_metadata, monkeypatch):
    profile = one_profile(wire, linked_metadata)
    path = tmp_path / "snapshot.parquet"
    result = write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    assert list(result) == [
        "schema_sha256",
        "rows",
        "profiles",
        "membership_sha256",
        "storage_comparison",
        "writer_options",
        "verification",
        "certificate",
    ]
    assert result["verification"] == "arrow-equality-v4"
    payload = path.read_bytes()
    certificate = result["certificate"]
    assert isinstance(certificate, PublicationSnapshotVerifier)
    assert certificate.digest == hashlib.sha256(payload).hexdigest()
    assert certificate.byte_count == len(payload)

    # Certified for exactly these bytes: no row-by-row pass, only the light checks.
    def forbidden(*args, **kwargs):
        raise AssertionError("certified bytes must not be decoded row by row again")

    monkeypatch.setattr(parquet, "verify_snapshot", forbidden)
    expected = {k: result[k] for k in ("schema_sha256", "rows", "profiles", "membership_sha256")}
    assert certificate(payload) == certificate(payload) == expected
    for changed in (payload[:-1], payload + b"x", bytes([payload[0] ^ 1]) + payload[1:]):
        with pytest.raises(Rejection, match="object_checksum_mismatch"):
            certificate(changed)


def test_certified_flag_decides_whether_the_first_call_verifies_fully(
    tmp_path, wire, linked_metadata, monkeypatch
):
    profile = one_profile(wire, linked_metadata)
    path = tmp_path / "snapshot.parquet"
    result = write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    payload = path.read_bytes()
    calls = []
    original = parquet.verify_snapshot

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(parquet, "verify_snapshot", counting)
    arguments = dict(
        digest=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        evidence=result,
        deadline=time.monotonic() + 10,
        budget_factory=lambda: contextual(CanonicalBudget()),
    )
    certified = PublicationSnapshotVerifier(**arguments, certified=True)
    certified(payload)
    certified(payload)
    assert not calls
    uncertified = PublicationSnapshotVerifier(**arguments)
    uncertified(payload)
    uncertified(payload)
    assert len(calls) == 1  # The first payload only; the certificate is then set.
    # A certified verifier still applies the light checks: wrong evidence counts.
    wrong = PublicationSnapshotVerifier(
        **dict(arguments, evidence=dict(result, rows=result["rows"] + 1)), certified=True
    )
    with pytest.raises(Rejection, match="object_validation_mismatch"):
        wrong(payload)


@contextmanager
def contextual(value):
    yield value


def test_budget_is_charged_only_for_encodes_performed(tmp_path, wire, linked_metadata):
    profile = one_profile(wire, linked_metadata)
    charged = []

    @contextmanager
    def budget():
        value = CanonicalBudget()
        yield value
        charged.append(value.run_used)

    write_snapshot(
        tmp_path / "plain.parquet",
        {uuid.uuid4(): profile},
        deadline=time.monotonic() + 10,
        budget_factory=budget,
    )
    assert charged == []  # No canonical encode happens on the Arrow path.
    write_snapshot(
        tmp_path / "audited.parquet",
        {uuid.uuid4(): profile},
        deadline=time.monotonic() + 10,
        budget_factory=budget,
        audit=True,
    )
    assert charged == [len(profile.canonical_bytes)]  # The audit re-encodes the profile once.


def test_audit_runs_row_by_row_and_must_agree(tmp_path, wire, linked_metadata, monkeypatch):
    profile = one_profile(wire, linked_metadata)
    calls = []
    original = parquet.verify_snapshot

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(parquet, "verify_snapshot", counting)
    write_snapshot(
        tmp_path / "one.parquet", {uuid.uuid4(): profile}, deadline=time.monotonic() + 10
    )
    assert not calls
    write_snapshot(
        tmp_path / "two.parquet",
        {uuid.uuid4(): profile},
        deadline=time.monotonic() + 10,
        audit=True,
    )
    assert len(calls) == 1

    def disagreeing(*args, **kwargs):
        return dict(original(*args, **kwargs), membership_sha256="0" * 64)

    monkeypatch.setattr(parquet, "verify_snapshot", disagreeing)
    with pytest.raises(Rejection, match="object_validation_mismatch"):
        write_snapshot(
            tmp_path / "three.parquet",
            {uuid.uuid4(): profile},
            deadline=time.monotonic() + 10,
            audit=True,
        )


def replace(table, name, values):
    field = schema().field(name)
    return table.set_column(table.column_names.index(name), field, pa.array(values, field.type))


def first_value(table, name):
    return table[name][0].as_py()


TAMPERS = {
    "profile_hash": (
        lambda t: replace(t, "profile_hash", ["a" * 64] * t.num_rows),
        "snapshot_scientific_hash_mismatch",
    ),
    "profile_content": (
        lambda t: replace(
            t, "profile_content", [first_value(t, "profile_content") + " "] * t.num_rows
        ),
        "snapshot_scientific_hash_mismatch",
    ),
    "canonical_level": (
        lambda t: replace(
            t,
            "canonical_level",
            [first_value(t, "canonical_level").replace("exact", "exacT", 1)]
            + t["canonical_level"].to_pylist()[1:],
        ),
        "snapshot_scientific_hash_mismatch",
    ),
    "pressure": (
        lambda t: replace(t, "pressure", [999.0] * t.num_rows),
        "snapshot_numeric_mismatch",
    ),
    "temperature_qc": (
        lambda t: replace(t, "temperature_qc", ["9"] * t.num_rows),
        "snapshot_level_mismatch",
    ),
    "flags": (
        lambda t: replace(t, "pressure_flags", [["tampered"]] * t.num_rows),
        "snapshot_level_mismatch",
    ),
    "level_index": (
        lambda t: replace(t, "level_index", [5] * t.num_rows),
        "snapshot_profile_inconsistency",
    ),
    "one_row_hash": (
        lambda t: replace(t, "profile_hash", ["a" * 64] + t["profile_hash"].to_pylist()[1:]),
        "snapshot_profile_inconsistency",
    ),
    "profile_id": (
        lambda t: replace(t, "profile_id", [str(uuid.UUID(int=999))] * t.num_rows),
        "snapshot_profile_inconsistency",
    ),
    "dropped_row": (lambda t: t.slice(0, t.num_rows - 1), "storage_comparison_mismatch"),
    "dropped_column": (
        lambda t: t.drop_columns(["profile_hash"]),
        "parquet_schema_mismatch",
    ),
    "schema_metadata": (
        lambda t: t.replace_schema_metadata({}),
        "parquet_schema_mismatch",
    ),
}


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_tampered_file_is_rejected_before_a_certificate_exists(
    tmp_path, wire, linked_metadata, monkeypatch, name
):
    change, category = TAMPERS[name]
    profile = one_profile(wire, linked_metadata)

    def reopen(path):
        pq.write_table(change(pq.read_table(path)), path)
        return pq.ParquetFile(path)

    monkeypatch.setattr(parquet, "_open_written", reopen)
    with pytest.raises(Rejection, match=category):
        write_snapshot(
            tmp_path / "snapshot.parquet", {uuid.uuid4(): profile}, deadline=time.monotonic() + 10
        )


def test_tampered_row_groups_are_rejected(tmp_path, wire, linked_metadata, monkeypatch):
    profile = one_profile(wire, linked_metadata)

    def regroup(size):
        def reopen(path):
            pq.write_table(pq.read_table(path), path, row_group_size=size)
            return pq.ParquetFile(path)

        return reopen

    monkeypatch.setattr(parquet, "_open_written", regroup(2))
    with pytest.raises(Rejection, match="storage_comparison_mismatch"):
        write_snapshot(
            tmp_path / "split.parquet", {uuid.uuid4(): profile}, deadline=time.monotonic() + 10
        )
    monkeypatch.setattr(parquet, "ROW_GROUP_ROWS", 2)  # Now the file has an oversized group.
    monkeypatch.setattr(parquet, "_open_written", regroup(3))
    with pytest.raises(Rejection, match="parquet_row_group_limit"):
        write_snapshot(
            tmp_path / "large.parquet", {uuid.uuid4(): profile}, deadline=time.monotonic() + 10
        )


def test_tampering_beyond_the_first_batch_is_found(tmp_path, monkeypatch):
    # Corrupt a level in the middle of a long profile that spans several read-back batches.
    items = synthetic_profiles((1, 699), (1, 300))
    monkeypatch.setattr(parquet, "VERIFY_BATCH_BYTES", 1)  # 64-row batches
    names = {"pressure": "snapshot_numeric_mismatch", "pressure_qc": "snapshot_level_mismatch"}
    for name, category in names.items():

        def reopen(path, name=name):
            table = pq.read_table(path)
            values = table[name].to_pylist()
            values[500] = 999.0 if name == "pressure" else "9"
            pq.write_table(replace(table, name, values), path)
            return pq.ParquetFile(path)

        monkeypatch.setattr(parquet, "_open_written", reopen)
        with pytest.raises(Rejection, match=category):
            write_snapshot(tmp_path / f"{name}.parquet", items, deadline=time.monotonic() + 30)


def test_identity_order_and_alias_checks(tmp_path, wire, linked_metadata):
    profile = one_profile(wire, linked_metadata)
    low, high = uuid.UUID(int=1), uuid.UUID(int=2)
    with pytest.raises(Rejection, match="snapshot_identity_order"):
        write_snapshot(
            tmp_path / "order.parquet",
            [(high, profile), (low, profile)],
            deadline=time.monotonic() + 10,
        )
    with pytest.raises(Rejection, match="duplicate_snapshot_alias"):
        write_snapshot(
            tmp_path / "alias.parquet",
            [(low, profile), (high, profile)],
            deadline=time.monotonic() + 10,
        )
    with pytest.raises(Rejection, match="snapshot_profile_inconsistency"):
        write_snapshot(
            tmp_path / "same.parquet",
            [(low, profile), (low, profile)],
            deadline=time.monotonic() + 10,
        )


def test_canonical_limits_are_enforced_with_readback_evidence(
    tmp_path, wire, linked_metadata, monkeypatch
):
    profile = one_profile(wire, linked_metadata)
    first = next(parquet.rows(uuid.UUID(int=1), profile))
    header, level = len(first["profile_content"]), len(first["canonical_level"])
    items = [(uuid.UUID(int=1), profile)]
    monkeypatch.setattr(parquet, "PROFILE_CANONICAL_LIMIT", header - 1)
    with pytest.raises(Rejection, match="canonical_output_limit") as error:
        write_snapshot(tmp_path / "header.parquet", items, deadline=time.monotonic() + 10)
    assert error.value.resource_evidence == {
        "scope": "profile",
        "operation": "readback",
        "limit_bytes": header - 1,
        "used_bytes": 0,
        "requested_bytes": header,
    }
    monkeypatch.setattr(parquet, "PROFILE_CANONICAL_LIMIT", header + level - 1)
    with pytest.raises(Rejection, match="canonical_output_limit") as error:
        write_snapshot(tmp_path / "level.parquet", items, deadline=time.monotonic() + 10)
    assert error.value.resource_evidence["used_bytes"] == header
    assert error.value.resource_evidence["requested_bytes"] == level
    monkeypatch.setattr(parquet, "PROFILE_CANONICAL_LIMIT", 16 * 1024 * 1024)
    monkeypatch.setattr(parquet, "PROFILE_LEVEL_LIMIT", len(profile.levels) - 1)
    with pytest.raises(Rejection, match="canonical_output_limit"):
        write_snapshot(tmp_path / "count.parquet", items, deadline=time.monotonic() + 10)


def test_snapshot_budget_and_deadline_rejections(tmp_path, wire, linked_metadata):
    profile = one_profile(wire, linked_metadata)
    items = [(uuid.UUID(int=1), profile)]
    with pytest.raises(Rejection, match="snapshot_deadline"):
        write_snapshot(tmp_path / "late.parquet", items, deadline=time.monotonic() - 1)
    with pytest.raises(Rejection, match="invalid_object_budget"):
        write_snapshot(
            tmp_path / "zero.parquet", items, deadline=time.monotonic() + 10, max_bytes=0
        )
    with pytest.raises(Rejection, match="object_size_limit"):
        write_snapshot(
            tmp_path / "small.parquet", items, deadline=time.monotonic() + 10, max_bytes=8
        )
    with pytest.raises(Rejection, match="empty_snapshot_not_publishable"):
        write_snapshot(tmp_path / "empty.parquet", [], deadline=time.monotonic() + 10)
    existing = tmp_path / "existing.parquet"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        write_snapshot(existing, items, deadline=time.monotonic() + 10)
    assert existing.read_bytes() == b"keep"
