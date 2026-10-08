"""Proposal tests do not authorize or activate source-policy amendments."""

import copy
import json
from pathlib import Path

import pytest
from floatchat_core.ingestion.numeric import decode_json
from source_policy_proposal import VERSION, empty_delivery, exclusion


def triple():
    return [
        {
            "role": role,
            "path": "/argo",
            "status": 404,
            "parameters": {
                "startDate": "2025-01-01T00:00:00Z",
                "endDate": "2025-01-08T00:00:00Z",
                "polygon": "approved-polygon",
                **({"data": "all"} if role == "profile" else {}),
            },
            "body": b"[]",
            "content_type": "application/json",
            "compressed_bytes": 2,
            "complete_framing": True,
        }
        for role in ("inventory_before", "profile", "inventory_after")
    ]


def test_proposal_inactive_without_deployed_attestation():
    assert VERSION.endswith("INACTIVE")
    assert not empty_delivery(triple())
    assert empty_delivery(triple(), deployed_compatible=True)
    current = copy.deepcopy(triple())
    for value in current:
        value["status"] = 200
    assert empty_delivery(current, deployed_compatible=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("body", b"["),
        ("body", b"{}"),
        ("body", b'[{"_id":"x"}]'),
        ("body", b"[]unexpected"),
        ("complete_framing", False),
        ("status", 200),
        ("content_type", "text/html"),
        ("path", "/argo/meta"),
        ("role", "metadata"),
        ("compressed_bytes", 32 * 1024**2 + 1),
        ("compressed_bytes", -1),
        ("complete_framing", "unverified"),
        ("content_type", None),
        ("body", None),
    ],
)
def test_proposal_rejects_ambiguous_empty(field, value):
    responses = triple()
    responses[0][field] = value
    assert not empty_delivery(responses, deployed_compatible=True)


@pytest.mark.parametrize("change", ["id", "unknown", "selection", "data", "inventory_data"])
def test_proposal_exact_collection_selection_parameters(change):
    responses = triple()
    if change == "id":
        responses[0]["parameters"] = {"id": "2904014_040"}
    elif change == "unknown":
        responses[0]["parameters"]["unexpected"] = "x"
    elif change == "selection":
        responses[0]["parameters"]["endDate"] = "2025-01-09T00:00:00Z"
    elif change == "data":
        responses[1]["parameters"]["data"] = "pressure"
    else:
        responses[0]["parameters"]["data"] = "all"
    assert not empty_delivery(responses, deployed_compatible=True)


def test_proposal_missing_capture_fields_fail_closed():
    responses = triple()
    responses[0].pop("body")
    assert not empty_delivery(responses, deployed_compatible=True)


def test_proposal_exclusion_preserves_identity_provenance_and_unknown_loss(wire, linked_metadata):
    profile = decode_json(json.dumps(wire).encode())
    profile["data_warning"] = ["degenerate_levels"]
    evidence = exclusion(profile, ["synthetic-selection"], "a" * 64, linked_metadata)
    assert evidence["returned_levels"] == 3 and evidence["lost_input_levels"] is None
    assert not evidence["scientific_measurements_accepted"]
    assert not evidence["previous_science_deletion_authorized"]
    assert evidence["raw_sha256"] == "a" * 64
    for warning in (["new_warning"], ["degenerate_levels", "new_warning"], []):
        with pytest.raises(ValueError, match="whole_chunk_quarantine"):
            exclusion(
                {**profile, "data_warning": warning}, ["selection"], "a" * 64, linked_metadata
            )


@pytest.mark.parametrize("change", ["unknown_column", "length", "unknown_attribute", "identity"])
def test_proposal_known_warning_cannot_bypass_schema_validation(change, wire, linked_metadata):
    profile = decode_json(json.dumps(wire).encode())
    profile["data_warning"] = ["degenerate_levels"]
    if change == "unknown_column":
        profile["data_info"][0][0] = "undocumented_column"
    elif change == "length":
        profile["data"][0].pop()
    elif change == "unknown_attribute":
        profile["unapproved"] = "value"
    else:
        profile.pop("_id")
    with pytest.raises(ValueError, match="whole_chunk_quarantine"):
        exclusion(profile, ["synthetic-selection"], "a" * 64, linked_metadata)


def test_production_policy_remains_strict_and_has_no_proposal_import():
    root = Path(__file__).resolve().parents[2]
    argovis = (root / "packages/core/src/floatchat_core/ingestion/argovis.py").read_text()
    assert 'raise Rejection("upstream_data_warning")' in argovis
    for folder in (root / "packages/core/src", root / "workers/src", root / "scripts"):
        for file in folder.rglob("*.py"):
            assert "source_policy_proposal" not in file.read_text()
