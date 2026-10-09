"""F01-2 synthetic transformations of admitted captures; never source observations."""

import hashlib
import json
from pathlib import Path

from floatchat_core.ingestion.numeric import decode_json

ROOT = Path(__file__).resolve().parents[2]


def admitted(mode):
    policy = json.loads((ROOT / "docs/stage1-f01-evidence-v2.json").read_bytes())
    basis = next(item for item in policy["derivative_basis"] if item["mode"] == mode)
    bundle = ROOT / basis["bundle"]
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == basis["manifest_sha256"]
    manifest = json.loads(manifest_bytes)
    records = {}
    evidence = {
        "kind": "labelled_synthetic_derivative_of_admitted_authentic_fixture",
        "evidence_version": policy["version"],
        "basis": basis,
        "attribution": manifest["attribution"],
        "source_versions": manifest["versions"],
        "payload_sha256": {},
        "mutations": [],
        "authentic_representation_claim": False,
    }
    for role in ("profile", "metadata"):
        response = next(item for item in manifest["responses"] if item["role"] == role)
        payload = (bundle / response["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == response["sha256"]
        records[role] = decode_json(payload)[0]
        evidence["payload_sha256"][role] = response["sha256"]
    assert records["profile"]["_id"] == basis["profile_id"]
    return records["profile"], {records["metadata"]["_id"]: records["metadata"]}, evidence


def core_null(mode):
    raw, metadata, evidence = admitted(mode)
    for index, variable in enumerate(("pressure", "temperature", "salinity"), start=1):
        column = raw["data_info"][0].index(variable)
        assert raw["data"][column][index] is not None
        raw["data"][column][index] = None
        evidence["mutations"].append({"column": variable, "level_index": index, "value": None})
    return raw, metadata, evidence


def descending():
    raw, metadata, evidence = admitted("R")
    assert raw["profile_direction"] == "A"
    raw["profile_direction"] = "D"
    evidence["mutations"].append({"field": "profile_direction", "from": "A", "to": "D"})
    return raw, metadata, evidence


def persist(name, provenance, **assertions):
    """Write only after the calling test's assertions pass; reports are not raw fixtures."""
    (ROOT / "reports" / ("stage1-f01-" + name + ".json")).write_text(
        json.dumps({"provenance": provenance, "passed_assertions": assertions}, indent=2) + "\n"
    )
