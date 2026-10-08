"""Explicitly synthetic supplement cases; no authentic A-mode/null evidence."""

import copy
import json
from pathlib import Path

import pytest
from floatchat_core.ingestion.argovis import (
    LEGACY_SOURCE_CONTRACT,
    SOURCE_CONTRACT,
    TRANSLATOR_REVISION,
    TRANSLATOR_SHA256,
    map_profile,
    policy_versions,
)
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.raw import sanitize_raw


def supplemental(wire):
    result = copy.deepcopy(wire)
    result["data_info"][0] += ["chla_fluorescence", "chla_fluorescence_qc"]
    result["data_info"][2] += [["ru", "A"], [None, None]]
    result["data"] += [[1, None, 3], [1, 2, "unknown"]]
    return result


def mapped(raw, metadata, **kwargs):
    return map_profile(decode_json(json.dumps(raw).encode()), metadata, CanonicalBudget(), **kwargs)


def test_G03_S03_exact_supplement_raw_preservation_and_version_pin(wire, linked_metadata):
    raw = supplemental(wire)
    clean = sanitize_raw(json.dumps(raw).encode())
    assert decode_json(clean.payload) == decode_json(json.dumps(raw).encode())
    ordinary = mapped(wire, linked_metadata)
    supplemented = mapped(raw, linked_metadata)
    assert supplemented.content_hash == ordinary.content_hash
    assert supplemented.levels == ordinary.levels
    assert supplemented.outside_core_arrays == ordinary.outside_core_arrays + 2
    assert all(not any("chla" in key for key in row) for row in supplemented.levels)
    with pytest.raises(Rejection, match="unknown_data_field"):
        mapped(raw, linked_metadata, source_contract=LEGACY_SOURCE_CONTRACT)
    pin = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/upstream/argovis-source-supplement-v1.json"
        ).read_text()
    )
    assert pin["translator_revision"] == TRANSLATOR_REVISION
    assert pin["translator_sha256"] == TRANSLATOR_SHA256
    assert pin["source_contract"] == SOURCE_CONTRACT
    assert pin["base_specification_sha256"] == policy_versions()["specification_sha256"]
    assert pin["exact_additional_noncore_names"] == ["chla_fluorescence", "chla_fluorescence_qc"]
    assert policy_versions()["translator_sha256"] == TRANSLATOR_SHA256
    assert "source_contract" not in policy_versions(LEGACY_SOURCE_CONTRACT)


@pytest.mark.parametrize(
    "name",
    [
        "chla_fluorescence_argoqc",
        "chla_fluorescence_std",
        "chla_fluorescence_qc_argoqc",
        "unrecognized",
    ],
)
def test_S03_supplement_has_no_wildcard_or_alias(wire, linked_metadata, name):
    raw = supplemental(wire)
    raw["data_info"][0][-1] = name
    with pytest.raises(Rejection, match="unknown_data_field"):
        mapped(raw, linked_metadata)


@pytest.mark.parametrize("damage", ["short", "empty", "object", "attributes"])
def test_S03_supplement_structure_and_alignment(wire, linked_metadata, damage):
    raw = supplemental(wire)
    if damage == "short":
        raw["data"][-1].pop()
    elif damage == "empty":
        raw["data"][-1] = []
    elif damage == "object":
        raw["data"][-1][0] = {"unexpected": 1}
    else:
        raw["data_info"][2][-2][0] = []
    with pytest.raises(Rejection):
        mapped(raw, linked_metadata)
