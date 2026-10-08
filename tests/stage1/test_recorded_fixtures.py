"""Authentic sanitized captures; fully offline, never access private originals."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from floatchat_core.ingestion.argovis import LEGACY_SOURCE_CONTRACT, _data_columns
from floatchat_core.ingestion.numeric import Rejection, decode_json

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "fixture_audit", ROOT / "scripts/audit_stage1_fixtures.py"
)
assert spec is not None and spec.loader is not None
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)
BUNDLE = ROOT / "tests/fixtures/argovis/recorded/6a8ffa52f6db4954b974c449e68c54bc"
ADDITIONAL = ROOT / "tests/fixtures/argovis/recorded/10b19b21ac4d4d8ba69a4fc95e87de3c"
R_MODE = ROOT / "tests/fixtures/argovis/recorded/25f21e056e7c4db7bc1e21b0a28ea45f"
A_MODE = ROOT / "tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45"
DISCOVERY = ROOT / "tests/fixtures/argovis/discovery/e5b3f14e549d49e69ed77fde03d40d8c"


def test_F01_S01_inventory_discovery_verifies_R_A_candidates_not_scientific_coverage():
    report = audit_module.audit_discovery(DISCOVERY)
    assert (
        report["manifest_sha256"]
        == "817569c15a627122db86e23ee1dba8dbbfc426a8c94bd0b65cadcedbf1ed8eab"
    )
    assert (
        report["response_sha256"]
        == "d4ce241fdca004776130aefbcfd1e0bc9208c3de3228d7966102349381976022"
    )
    assert report["verified_response_bytes"] == 2281
    assert report["received_compressed_bytes"] == 2286
    assert report["retrieved_at_utc"] == "2026-10-06T13:00:14.602107+00:00"
    candidates = {item["source_profile_id"]: item for item in report["candidates"]}
    assert set(candidates) == {"2904014_040", "6990616_100"}
    for identifier, mode in (("6990616_100", "R"), ("2904014_040", "A")):
        candidate = candidates[identifier]
        assert candidate["inventory_core_data_keys_modes"] == {
            "pressure": mode,
            "temperature": mode,
            "salinity": mode,
        }
        assert candidate["inventory_direction"] == "A"
        assert not candidate["complete_capture"]
        assert candidate["measurement_levels"] == "not_fetched"
    assert candidates["6990616_100"]["inventory_schema_compatible"]
    assert candidates["6990616_100"]["unsupported_inventory_columns"] == []
    assert not candidates["2904014_040"]["inventory_schema_compatible"]
    assert candidates["2904014_040"]["unsupported_inventory_columns"] == [
        "chla_fluorescence",
        "chla_fluorescence_qc",
    ]
    assert report["F01_representations_closed"] == []
    assert report["regional_completeness"] == "not_proven_by_inventory_discovery"
    corpus = audit_module.audit_corpus()
    assert corpus["response_count"] == 20 and corpus["distinct_profile_count"] == 5
    assert "data_mode_R" not in corpus["representation_gaps"]
    assert "data_mode_A" not in corpus["representation_gaps"]


def test_F01_S02_synthetic_shape_from_inventory_rejects_undocumented_fields():
    # Only names/attributes are authentic inventory evidence. These one-element
    # null arrays are a labelled synthetic shape, never claimed as captured data.
    inventories = json.loads((DISCOVERY / "01-inventory_discovery.json").read_bytes())
    inventory = next(row for row in inventories if row["_id"] == "2904014_040")
    document = {
        "data_info": inventory["data_info"],
        "data": [[None] for _ in inventory["data_info"][0]],
    }
    with pytest.raises(Rejection, match="unknown_data_field"):
        _data_columns(document, source_contract=LEGACY_SOURCE_CONTRACT)
    columns, _, count = _data_columns(document)
    assert count == 1 and set(columns) == set(inventory["data_info"][0])


def test_F01_inventory_discovery_replaced_payload_fails_checksum(monkeypatch):
    original = Path.read_bytes

    def changed(path):
        data = original(path)
        return data + b" " if path == DISCOVERY / "01-inventory_discovery.json" else data

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(Rejection, match="discovery_response_mismatch"):
        audit_module.audit_discovery(DISCOVERY)


def test_F01_inventory_discovery_unapproved_endpoint_rejected(monkeypatch):
    original = Path.read_bytes

    def changed(path):
        data = original(path)
        if path == DISCOVERY / "manifest.json":
            manifest = json.loads(data)
            manifest["endpoint"] = "https://unexpected.invalid/argo"
            return json.dumps(manifest).encode()
        return data

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(Rejection, match="discovery_provenance_mismatch"):
        audit_module.audit_discovery(DISCOVERY)


def test_F01_inventory_discovery_rejects_external_directory_without_reading(tmp_path, monkeypatch):
    def forbidden(path):
        pytest.fail("Unapproved path must be rejected before reading any file")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(Rejection, match="unapproved_sanitized_discovery"):
        audit_module.audit_discovery(tmp_path)


def test_F01_S01_S03_S04_authentic_13857_is_D_QC2_missing_salinity_not_R():
    report = audit_module.audit(ADDITIONAL)
    assert (
        report["manifest_sha256"]
        == "d65c72afd189be392d4c3335ca88803cffa291fb904e2d6ae8daaff1ed3a2e2f"
    )
    assert len(report["verified_responses"]) == 4
    assert {item["role"] for item in report["verified_responses"]} == {
        "inventory_before",
        "profile",
        "inventory_after",
        "metadata",
    }
    (profile,) = report["profiles"]
    assert profile["source_profile_id"] == "13857_068" and profile["levels"] == 103
    assert (
        profile["scientific_sha256"]
        == "13656548049786e4452cd06e65b95fc274a6268a3e486af572b184645edeb3c2"
    )
    assert profile["direction"] == "A" and profile["source_revision_components"] == 1
    assert not profile["in_indian_ocean_geometry"]
    assert profile["source_columns"] == [
        "pressure",
        "pressure_argoqc",
        "temperature",
        "temperature_argoqc",
    ]
    for name in ("pressure", "temperature"):
        variable = profile["variables"][name]
        assert variable["raw_data_keys_modes"] == variable["modes"] == ["D"]
        assert variable["qc_values"] == ["2"]
        assert variable["available"] == {
            "original": 0,
            "_adjusted": 103,
            "_qc": 0,
            "_adjusted_qc": 103,
            "_error": 0,
            "_original_error": 0,
        }
    salinity = profile["variables"]["salinity"]
    assert not salinity["source_column_present"] and salinity["modes"] == []
    assert all(value == 0 for value in salinity["available"].values())
    assert profile["source_core_value_null_cells"] == profile["source_core_qc_null_cells"] == 0
    assert not profile["repeated_nonnull_pressure"]
    assert "data_mode_R" in report["representation_gaps"]


def test_F01_S01_S03_S04_authentic_6990616_R_original_values_QC_and_hashes():
    report = audit_module.audit(R_MODE)
    assert (
        report["manifest_sha256"]
        == "7127115c0b866861e11f1ab34c3cda5c0d4633e885fa6687ba5d6d4112414dc6"
    )
    assert len(report["verified_responses"]) == 4
    assert {item["role"] for item in report["verified_responses"]} == {
        "inventory_before",
        "profile",
        "inventory_after",
        "metadata",
    }
    (profile,) = report["profiles"]
    assert profile["source_profile_id"] == "6990616_100" and profile["levels"] == 43
    assert (
        profile["scientific_sha256"]
        == "eb5f397e8626fa8146fc41faed6d39ce49c233059dfeb3c77a95c833db5f7eb7"
    )
    assert profile["direction"] == "A" and profile["source_revision_components"] == 1
    assert profile["in_indian_ocean_geometry"]
    assert profile["observed_at_utc"] == "2026-10-02T13:58:36.999000+00:00"
    for variable in profile["variables"].values():
        assert variable["source_column_present"]
        assert variable["raw_data_keys_modes"] == variable["modes"] == ["R"]
        assert variable["qc_values"] == ["1"]
        assert variable["available"] == {
            "original": 43,
            "_adjusted": 0,
            "_qc": 43,
            "_adjusted_qc": 0,
            "_error": 0,
            "_original_error": 0,
        }
    assert profile["source_core_value_null_cells"] == profile["source_core_qc_null_cells"] == 0
    assert not profile["repeated_nonnull_pressure"]
    assert "data_mode_R" not in report["representation_gaps"]
    assert report["regional_completeness"] == "not_proven_by_profile_id_samples"


def test_F01_complete_authentic_corpus_R_A_observed_two_authentic_gaps_remain():
    corpus = audit_module.audit_corpus()
    assert corpus["response_count"] == 20 and corpus["distinct_profile_count"] == 5
    assert corpus["captured_level_occurrences"] == 1162
    assert len(corpus["bundle_audits"]) == 4
    assert corpus["representation_gaps"] == [
        "direction_D",
        "source_core_measurement_null",
    ]
    assert corpus["minimum_F01_satisfied"]
    assert corpus["required_authentic_gaps"] == []
    assert corpus["waived_authentic_coverage_gaps"] == corpus["representation_gaps"]
    assert corpus["evidence_amendment"]["version"] == "F01-2"
    matrix = corpus["coverage_matrix"]
    assert matrix["data_mode_R"]["status"] == "observed"
    assert matrix["data_mode_R"]["witnesses"] == [
        {
            "bundle": str(R_MODE.relative_to(ROOT)),
            "source_profile_id": "6990616_100",
            "scientific_sha256": "eb5f397e8626fa8146fc41faed6d39ce49c233059dfeb3c77a95c833db5f7eb7",
        }
    ]
    assert matrix["data_mode_D"]["status"] == matrix["direction_A"]["status"] == "observed"
    assert matrix["data_mode_A"] == {
        "status": "observed",
        "witnesses": [
            {
                "bundle": str(A_MODE.relative_to(ROOT)),
                "source_profile_id": "2904014_040",
                "scientific_sha256": (
                    "a57bfef74f81d4d1344b9002aa14040969af2a75f65de50fdc4b21a87b4bbda3"
                ),
            }
        ],
    }
    assert matrix["supplied_core_qc"]["status"] == "observed"
    assert matrix["source_revision_metadata"]["status"] == "observed"
    for key in corpus["representation_gaps"]:
        assert matrix[key] == {
            "status": "authentic_unobserved_requirement_waived",
            "witnesses": [],
        }
    for key in ("repeated_nonnull_pressure", "supplied_measurement_error"):
        assert matrix[key] == {"status": "authentic_not_required", "witnesses": []}
    assert (
        "no authentic parser claim" in corpus["F01_evidence_policy"]["supplied_measurement_error"]
    )
    assert corpus["regional_completeness"] == "not_proven_by_profile_id_samples"


def test_F01_S01_S03_S04_authentic_2904014_A_adjusted_values_QC_and_provenance():
    report = audit_module.audit(A_MODE)
    assert (
        report["manifest_sha256"]
        == "f42b03e44588560ba43151428405eb4b40324a6d26dc3111406a41c56d0ff540"
    )
    assert len(report["verified_responses"]) == 4
    assert {row["role"] for row in report["verified_responses"]} == {
        "inventory_before",
        "profile",
        "inventory_after",
        "metadata",
    }
    assert report["versions"] == audit_module.policy_versions()
    assert report["attribution"]["argo_doi"] == "https://doi.org/10.17882/42182"
    (profile,) = report["profiles"]
    assert profile["source_profile_id"] == "2904014_040" and profile["levels"] == 501
    assert (
        profile["scientific_sha256"]
        == "a57bfef74f81d4d1344b9002aa14040969af2a75f65de50fdc4b21a87b4bbda3"
    )
    assert profile["direction"] == "A" and profile["source_revision_components"] == 2
    assert profile["in_indian_ocean_geometry"]
    assert profile["observed_at_utc"] == "2026-10-04T03:18:17.000000+00:00"
    for name, variable in profile["variables"].items():
        assert variable["source_column_present"]
        assert variable["raw_data_keys_modes"] == variable["modes"] == ["A"]
        assert variable["available"] == {
            "original": 0,
            "_adjusted": 501,
            "_qc": 0,
            "_adjusted_qc": 501,
            "_error": 0,
            "_original_error": 0,
        }
        assert variable["qc_values"] == (["1"] if name == "pressure" else ["1", "4"])
    assert not profile["repeated_nonnull_pressure"]
    assert profile["source_core_value_null_cells"] == profile["source_core_qc_null_cells"] == 0
    assert report["regional_completeness"] == "not_proven_by_profile_id_samples"
    assert profile["source_null_cells_by_column"] == {"nitrate": 501, "nitrate_argoqc": 501}
    assert profile["supplementary_noncore_columns"] == {
        name: {
            "levels": 501,
            "null_cells": 0,
            "source_attributes": attrs,
            "disposition": "immutable_raw_only_no_canonical_chlorophyll_mapping",
        }
        for name, attrs in (
            ("chla_fluorescence", {"units": "ru", "data_keys_mode": "A"}),
            ("chla_fluorescence_qc", {"units": None, "data_keys_mode": None}),
        )
    }


def test_F01_S01_authentic_noncore_nulls_do_not_close_core_null_gap():
    profile = audit_module.audit(A_MODE)["profiles"][0]
    document = decode_json((A_MODE / "02-profile.json").read_bytes())[0]
    columns, _, count = _data_columns(document)
    assert count == 501 and profile["source_null_cells"] == 1002
    assert {name: values.count(None) for name, values in columns.items() if None in values} == {
        "nitrate": 501,
        "nitrate_argoqc": 501,
    }
    assert "source_core_measurement_null" in audit_module.representation_gaps([profile])


def test_F01_S01_S02_authentic_fluorescence_supplement_keeps_raw_values_QC_attributes():
    before = (A_MODE / "02-profile.json").read_bytes()
    document = decode_json(before)[0]
    columns, attributes, count = _data_columns(document)
    assert count == 501
    assert columns["chla_fluorescence"][:3] == [
        Decimal("0.065268"),
        Decimal("0.071391"),
        Decimal("0.06935"),
    ]
    assert columns["chla_fluorescence_qc"][:3] == [1, 1, 1]
    assert len(columns["chla_fluorescence"]) == len(columns["chla_fluorescence_qc"]) == 501
    assert attributes["chla_fluorescence"] == {"units": "ru", "data_keys_mode": "A"}
    assert attributes["chla_fluorescence_qc"] == {"units": None, "data_keys_mode": None}
    with pytest.raises(Rejection, match="unknown_data_field"):
        _data_columns(document, source_contract=LEGACY_SOURCE_CONTRACT)
    assert (A_MODE / "02-profile.json").read_bytes() == before


def test_F01_missing_QC_or_variable_does_not_prove_source_value_null():
    # Labelled synthetic audit mutation, never an invented recorded response.
    profile = audit_module.audit(ADDITIONAL)["profiles"][0]
    profile["source_core_qc_null_cells"] = profile["source_core_null_cells"] = 1
    assert profile["source_core_value_null_cells"] == 0
    assert "source_core_measurement_null" in audit_module.representation_gaps([profile])


def test_F01_authentic_sanitized_inventory_metadata_hashes_and_coverage():
    report = audit_module.audit(BUNDLE)
    assert len(report["verified_responses"]) == 8
    assert [
        (row["source_profile_id"], row["levels"], row["scientific_sha256"])
        for row in report["profiles"]
    ] == [
        ("1901094_109", 92, "4720d3534449499d5fc67703e9c04a719c63b776600aab98d1111bbd42e8e0d4"),
        ("4901283_003", 423, "e0e9bb008a98fec66e47ffdffd987d2548ff94de6d456a608aced14e65474782"),
    ]
    assert report["representation_gaps"] == [
        "data_mode_R",
        "data_mode_A",
        "direction_D",
        "source_core_measurement_null",
    ]
    assert [row["source_revision_components"] for row in report["profiles"]] == [1, 2]
    for row in report["profiles"]:
        assert row["direction"] == "A"
        assert not row["in_indian_ocean_geometry"]
        for variable in row["variables"].values():
            assert variable["modes"] == ["D"]
            assert variable["available"]["_adjusted"] == row["levels"]
            assert variable["available"]["_adjusted_qc"] == row["levels"]
            assert variable["available"]["original"] == variable["available"]["_error"] == 0
            assert variable["qc_values"] == ["1"]
    assert report["F01_representative_corpus"] == "pending"
    assert report["regional_completeness"] == "not_proven_by_profile_id_samples"
    assert report["private_originals"] == "not_accessed"


def test_F01_audit_refuses_non_recorded_directory(tmp_path):
    with pytest.raises(Rejection, match="unapproved_sanitized_bundle"):
        audit_module.audit(tmp_path)


def test_F01_replaced_payload_fails_checksum(monkeypatch):
    original = Path.read_bytes

    def changed(path):
        data = original(path)
        return data + b" " if path == BUNDLE / "02-profile.json" else data

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(Rejection, match="fixture_response_mismatch"):
        audit_module.audit(BUNDLE)
