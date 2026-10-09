"""Scientific outputs must stay byte-identical to the stage1-v3 goldens (scripts/stage1_goldens.py).

Any execution-model change (decoder, encoder, mapper, writer, publication path)
must leave these values unchanged. A scientific rule change regenerates the file
under a new ADR and records the commit.
"""

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import write_snapshot
from floatchat_core.ingestion.raw import sanitize_raw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from stage1_goldens import mutations, profile_record  # noqa: E402
from stage1_perf_profile import BASES, synthetic_chunk  # noqa: E402

GOLDENS = json.loads((ROOT / "tests/fixtures/golden/stage1_v3_goldens.json").read_text())
RECORDED = ROOT / "tests/fixtures/argovis/recorded"


def _metadata(bundle, manifest):
    metadata = {}
    for response in manifest["responses"]:
        if response["role"] == "metadata":
            for item in decode_json((bundle / response["path"]).read_bytes()):
                metadata[item["_id"]] = item
    return metadata


@pytest.mark.parametrize("name", sorted(GOLDENS["bundles"]))
def test_recorded_bundle_outputs_are_byte_identical(name):
    bundle = RECORDED / name
    manifest = json.loads((bundle / "manifest.json").read_text())
    metadata = _metadata(bundle, manifest)
    expected = GOLDENS["bundles"][name]
    for response in manifest["responses"]:
        raw = (bundle / response["path"]).read_bytes()
        cleaned = sanitize_raw(raw, "synthetic-credential-sentinel")
        golden = expected["raw"][response["path"]]
        assert hashlib.sha256(raw).hexdigest() == golden["input_sha256"]
        assert hashlib.sha256(cleaned.payload).hexdigest() == golden["sanitized_sha256"]
        if response["role"] != "profile":
            continue
        for document in documents(raw):
            profile = map_profile(document, metadata, CanonicalBudget())
            assert profile_record(profile) == expected["profiles"][document["_id"]]
            for label, mutated in mutations(document).items():
                key = document["_id"] + ":" + label
                try:
                    actual = profile_record(map_profile(mutated, metadata, CanonicalBudget()))
                except Rejection as error:
                    actual = {"rejection": error.category}
                assert actual == expected["mutations"][key], key


@pytest.mark.parametrize("label", sorted(BASES))
def test_synthetic_clone_and_snapshot_are_byte_identical(label, tmp_path):
    payload, _, metadata = synthetic_chunk(3, 699, basis=BASES[label])
    expected = GOLDENS["synthetic"][f"{label}-3x699"]
    assert hashlib.sha256(payload).hexdigest() == expected["payload_sha256"]
    assert hashlib.sha256(sanitize_raw(payload).payload).hexdigest() == expected["sanitized_sha256"]
    meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    profiles = [map_profile(d, meta, CanonicalBudget()) for d in documents(payload)]
    assert [profile_record(p) for p in profiles] == expected["profiles"]
    verified = write_snapshot(
        tmp_path / "snapshot.parquet",
        [(uuid.UUID(int=index + 1), profile) for index, profile in enumerate(profiles)],
        deadline=time.monotonic() + 600,
    )
    assert {k: verified[k] for k in expected["snapshot"]} == expected["snapshot"]
