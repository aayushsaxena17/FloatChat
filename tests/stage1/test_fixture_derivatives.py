"""Labelled derivatives of authentic R capture; never additional source evidence."""

import json
import time
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from derivative_evidence import admitted, core_null, descending, persist
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json, scientific_number
from floatchat_core.ingestion.parquet import verify_snapshot, write_snapshot

BUNDLE = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/argovis/recorded/25f21e056e7c4db7bc1e21b0a28ea45f"
)


def recorded():
    raw = decode_json((BUNDLE / "02-profile.json").read_bytes())[0]
    meta = decode_json((BUNDLE / "04-metadata.json").read_bytes())[0]
    return raw, {meta["_id"]: meta}


def test_F01_I04_S05_labelled_repeated_pressure_derivative_preserves_ordinals(tmp_path):
    raw, metadata = recorded()
    pressure = raw["data_info"][0].index("pressure")
    # Explicit synthetic mutation; the recorded response stays immutable.
    raw["data"][pressure][1] = raw["data"][pressure][0]
    profile = map_profile(raw, metadata, CanonicalBudget())
    assert len(profile.levels) == 43
    assert profile.levels[0]["pressure"] == profile.levels[1]["pressure"]
    assert "repeated_pressure" in profile.levels[1]["pressure_flags"]
    path = tmp_path / "synthetic-repeated-pressure.parquet"
    write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    assert verify_snapshot(path, deadline=time.monotonic() + 10)["rows"] == 43
    table = pq.read_table(path)
    assert table["level_index"].to_pylist() == list(range(43))

    assert table["pressure"].to_pylist()[0] == table["pressure"].to_pylist()[1]


def test_F01_S01_labelled_normalized_errors_parquet_not_Argovis_wire(tmp_path):
    raw, metadata = recorded()
    profile = map_profile(raw, metadata, CanonicalBudget())
    # Model-layer synthesis only: no API field is invented and map_profile is
    # never claimed to extract these errors from this authentic response.
    content = json.loads(profile.canonical_bytes)
    levels = [dict(row) for row in profile.levels]
    for variable, token in (("pressure", "0.05"), ("temperature", "0.01"), ("salinity", "0.02")):
        number = scientific_number(Decimal(token))
        for row, canonical in zip(levels, content["levels"], strict=True):
            row[variable + "_original_error"] = number.value
            canonical[variable + "_original_error"] = number.canonical()
    encoded, digest = CanonicalBudget().encode(content)
    synthetic = replace(profile, levels=tuple(levels), canonical_bytes=encoded, content_hash=digest)
    assert synthetic.content_hash != profile.content_hash
    path = tmp_path / "synthetic-normalized-errors.parquet"
    write_snapshot(path, {uuid.uuid4(): synthetic}, deadline=time.monotonic() + 10)
    assert verify_snapshot(path, deadline=time.monotonic() + 10)["rows"] == 43
    table = pq.read_table(path)
    for variable, value in (("pressure", 0.05), ("temperature", 0.01), ("salinity", 0.02)):
        assert table[variable + "_original_error"].to_pylist() == [value] * 43
        assert table[variable + "_error"].to_pylist() == [None] * 43


def test_F01_I01_I02_I03_labelled_descending_identity_canonical_parquet(tmp_path):
    ascending_raw, metadata, _ = admitted("R")
    raw, _, provenance = descending()
    ascending = map_profile(ascending_raw, metadata, CanonicalBudget())
    profile = map_profile(raw, metadata, CanonicalBudget())
    assert provenance["authentic_representation_claim"] is False
    assert provenance["mutations"] == [{"field": "profile_direction", "from": "A", "to": "D"}]
    assert profile.direction == json.loads(profile.canonical_bytes)["direction"] == "D"
    assert profile.source_profile_id == ascending.source_profile_id
    assert profile.identity == ascending.identity  # Stable upstream ID takes precedence.
    assert profile.content_hash != ascending.content_hash
    assert profile.levels == ascending.levels
    assert profile.natural_key != ascending.natural_key
    del raw["_id"], ascending_raw["_id"]  # Explicit additional synthetic identity mutation.
    fallback = map_profile(raw, metadata, CanonicalBudget())
    other = map_profile(ascending_raw, metadata, CanonicalBudget())
    assert fallback.source_profile_id is other.source_profile_id is None
    assert fallback.identity != other.identity
    assert fallback.natural_key[2] == "D" and other.natural_key[2] == "A"
    path = tmp_path / "synthetic-descending.parquet"
    write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    assert verify_snapshot(path, deadline=time.monotonic() + 10)["rows"] == 43
    table = pq.read_table(path)
    assert [json.loads(value)["direction"] for value in table["profile_content"].to_pylist()] == [
        "D"
    ] * 43
    assert table["level_index"].to_pylist() == list(range(43))
    persist(
        "descending-unit",
        provenance,
        direction=profile.direction,
        scientific_sha256=profile.content_hash,
        stable_upstream_id_preferred=True,
        fallback_directions_do_not_collide=True,
        canonical_and_parquet_direction="D",
        rows=43,
        extra_identity_test_mutation="remove _id in both A/D copies",
    )


@pytest.mark.parametrize("mode", ["R", "A"])
def test_F01_S01_S03_S04_labelled_present_core_null_parser_canonical_parquet(mode, tmp_path):
    baseline_raw, metadata, _ = admitted(mode)
    raw, _, provenance = core_null(mode)
    baseline = map_profile(baseline_raw, metadata, CanonicalBudget())
    profile = map_profile(raw, metadata, CanonicalBudget())
    assert provenance["evidence_version"] == "F01-2"
    assert provenance["authentic_representation_claim"] is False
    assert len(provenance["mutations"]) == 3
    assert len(profile.levels) == len(baseline.levels)
    assert profile.identity == baseline.identity and profile.content_hash != baseline.content_hash
    content = json.loads(profile.canonical_bytes)
    suffix = "" if mode == "R" else "_adjusted"
    counterpart = "_adjusted" if mode == "R" else ""
    for index, variable in enumerate(("pressure", "temperature", "salinity"), start=1):
        assert variable in raw["data_info"][0]
        row = profile.levels[index]
        assert row[variable + suffix] is None
        canonical = content["levels"][index][variable + suffix]
        assert canonical == {
            "exact": None,
            "missing_reason": "null",
            "nonfinite_kind": None,
            "flags": [],
        }
        assert content["levels"][index][variable + counterpart] is None
        assert "variable_absent" not in row[variable + "_flags"]
        for field in ("_unit", "_unit_source", "_data_mode", suffix + "_qc", suffix + "_qc_source"):
            assert row[variable + field] == baseline.levels[index][variable + field]
        assert row[variable + suffix + "_qc"] is not None
    assert map_profile(raw, metadata, CanonicalBudget()).content_hash == profile.content_hash
    path = tmp_path / ("synthetic-present-core-null-" + mode + ".parquet")
    write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    assert verify_snapshot(path, deadline=time.monotonic() + 10)["rows"] == len(profile.levels)
    table = pq.read_table(path)
    assert table["level_index"].to_pylist() == list(range(len(profile.levels)))
    for index, variable in enumerate(("pressure", "temperature", "salinity"), start=1):
        assert table[variable + suffix].null_count == 1
        assert table[variable + suffix].to_pylist()[index] is None
        assert table[variable + suffix + "_qc"].to_pylist()[index] is not None
        assert table[variable + "_data_mode"].to_pylist()[index] == mode
    persist(
        "core-null-unit-" + mode,
        provenance,
        scientific_sha256=profile.content_hash,
        rows=len(profile.levels),
        selected_value_nulls_per_core_variable=1,
        matching_QC_unit_mode_and_ordinals_preserved=True,
        canonical_missing_reason="null",
        parser_canonical_parquet_verified=True,
    )


def test_F01_S01_labelled_null_distinctions_absence_QC_counterpart_noncore():
    raw, metadata, _ = admitted("R")
    # A synthetic absent variable removes its value AND QC columns.
    for name in ("salinity_argoqc", "salinity"):
        index = raw["data_info"][0].index(name)
        del raw["data_info"][0][index], raw["data_info"][2][index], raw["data"][index]
    # A synthetic missing QC changes only QC; the measurement remains present.
    index = raw["data_info"][0].index("temperature_argoqc")
    raw["data"][index][0] = None
    profile = map_profile(raw, metadata, CanonicalBudget())
    row = profile.levels[0]
    assert row["salinity"] is None and "variable_absent" in row["salinity_flags"]
    assert row["temperature"] is not None and row["temperature_qc"] is None
    assert row["temperature_adjusted"] is None and row["temperature_data_mode"] == "R"
    raw, metadata, _ = admitted("A")
    columns = dict(zip(raw["data_info"][0], raw["data"], strict=True))
    assert columns["nitrate"].count(None) == columns["nitrate_argoqc"].count(None) == 501
    adjusted = map_profile(raw, metadata, CanonicalBudget())
    for row in adjusted.levels:
        for variable in ("pressure", "temperature", "salinity"):
            assert row[variable + "_adjusted"] is not None and row[variable] is None
