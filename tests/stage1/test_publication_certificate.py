"""Whole-byte certificates retain scientific verification and recovery charging."""

import hashlib
import json
import time
import uuid
from contextlib import contextmanager

import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.parquet import PublicationSnapshotVerifier, write_snapshot


def certificate(tmp_path, wire, linked_metadata, **changes):
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    file = tmp_path / "certified.parquet"
    proof = write_snapshot(file, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
    payload = file.read_bytes()
    conversions = []

    @contextmanager
    def budget():
        value = CanonicalBudget()
        yield value
        conversions.append(value.run_used)

    arguments = dict(
        digest=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        evidence=proof,
        deadline=time.monotonic() + 10,
        budget_factory=budget,
    )
    arguments.update(changes)
    return payload, profile, conversions, arguments


def test_P02_N08_certificate_reuses_only_equal_whole_bytes_and_recovers_without_cache(
    tmp_path, wire, linked_metadata
):
    payload, profile, counts, args = certificate(tmp_path, wire, linked_metadata)
    check = PublicationSnapshotVerifier(**args)
    expected = check(payload)
    assert counts == [len(profile.canonical_bytes)]
    assert check(payload) == expected and check(payload) == expected
    assert counts == [len(profile.canonical_bytes)]
    for corrupted in (payload[:-1], payload + b"x", bytes([payload[0] ^ 1]) + payload[1:]):
        with pytest.raises(Rejection, match="object_checksum_mismatch"):
            check(corrupted)
    assert counts == [len(profile.canonical_bytes)]
    expected["rows"] = -1  # A returned dictionary cannot poison its certificate.
    assert check(payload)["rows"] == len(profile.levels)
    recovery = PublicationSnapshotVerifier(**args)
    assert recovery(payload)["rows"] == len(profile.levels)
    assert counts == [len(profile.canonical_bytes)] * 2


def test_P02_certificate_rejects_bad_local_evidence_and_expired_deadline(
    tmp_path, wire, linked_metadata
):
    payload, _, counts, args = certificate(tmp_path, wire, linked_metadata)
    args["evidence"] = dict(args["evidence"], rows=999)
    with pytest.raises(Rejection, match="object_validation_mismatch"):
        PublicationSnapshotVerifier(**args)(payload)
    assert len(counts) == 1
    args["deadline"] = time.monotonic() - 1
    with pytest.raises(Rejection, match="snapshot_deadline"):
        PublicationSnapshotVerifier(**args)(payload)
    assert len(counts) == 1
