"""The bounded fast encoder changes neither canonical bytes nor budget failures."""

import hashlib
import json
from pathlib import Path

import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import (
    CanonicalBudget,
    Rejection,
    decode_json,
)


def test_admitted_501_level_science_has_identical_bytes_hash_and_charge():
    root = Path(__file__).resolve().parents[2]
    bundle = root / "tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45"
    metadata = {d["_id"]: d for d in decode_json((bundle / "04-metadata.json").read_bytes())}
    source = decode_json((bundle / "02-profile.json").read_bytes())[0]
    # The capacity derivatives reserialize the admitted JSON before changing
    # only their declared header fields. Exact Decimal measurements/QC/attributes
    # must survive that serialization, not merely their rounded float64 values.
    reserialized = decode_json(
        json.dumps(json.loads((bundle / "02-profile.json").read_bytes())).encode()
    )[0]
    assert source["data"] == reserialized["data"]
    assert source["data_info"] == reserialized["data_info"]
    budget = CanonicalBudget()
    profile = map_profile(source, metadata, budget)
    reference = json.dumps(
        json.loads(profile.canonical_bytes), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert len(profile.levels) == 501 and reference == profile.canonical_bytes
    assert profile.content_hash == hashlib.sha256(reference).hexdigest()
    assert budget.run_used == budget.chunk_used == len(reference)


@pytest.mark.parametrize(
    "level",
    [
        {"unicode": '\U0001f30a\u00e9\n\\"', "value": None, "qc": "1"},
        {"numbers": [0, -1, 1.25, 1e-100, 1e100], "flags": [True, False]},
        {"nested": {"b": ["0.10000000000000001", None], "a": "adjusted"}},
    ],
)
def test_bounded_c_level_encoding_matches_canonical_reference(level):
    content = {"z": None, "levels": [level, level], "a": "profile"}
    reference = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    budget = CanonicalBudget()
    actual, digest = budget.encode(content)
    assert actual == reference and digest == hashlib.sha256(reference).hexdigest()
    assert budget.run_used == budget.chunk_used == len(reference)


@pytest.mark.parametrize("scope", ["profile", "chunk", "run"])
def test_near_boundary_preserves_original_failure_and_charging(scope):
    content = {"a": 1, "levels": [{"value": "123456789", "qc": "1"}]}
    pieces = list(json.JSONEncoder(sort_keys=True, separators=(",", ":")).iterencode(content))
    limit = len("".join(pieces).encode()) - 1
    consumed = 0
    expected = None
    for piece in pieces:
        size = len(piece.encode())
        if consumed + size > limit:
            expected = (consumed, size)
            break
        consumed += size
    budget = CanonicalBudget(**{scope + "_limit": limit})
    with pytest.raises(Rejection) as caught:
        budget.encode(content)
    assert caught.value.resource_evidence == {
        "scope": scope,
        "operation": "encoding",
        "limit_bytes": limit,
        "used_bytes": expected[0],
        "requested_bytes": expected[1],
    }
    assert budget.run_used == budget.chunk_used == sum(expected)
    exact = CanonicalBudget(**{scope + "_limit": limit + 1})
    assert exact.encode(content)[0] == "".join(pieces).encode()


def test_nonfinite_values_keep_fail_closed_json_behavior():
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            CanonicalBudget().encode({"levels": [{"value": value}]})
