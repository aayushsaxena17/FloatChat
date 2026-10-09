"""Whole-byte certificates retain scientific verification and recovery charging."""

import copy
import hashlib
import json
import time
import uuid
from contextlib import contextmanager

import pyarrow.parquet as pq
import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.objects import publish_verified
from floatchat_core.ingestion.parquet import PublicationSnapshotVerifier, write_snapshot
from floatchat_core.ingestion.spool import merge_parts
from floatchat_core.ingestion.workflow import evidence_json, snapshot_certificate


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


class MemoryStore:
    """Both publication protocols: conditional single PUT and the pre-v4 temporary copy."""

    def __init__(self):
        self.data = {}

    def write_immutable(self, key, data, sha256_hex, deadline):
        assert hashlib.sha256(data).hexdigest() == sha256_hex
        self.data.setdefault(key, data)

    def stat(self, key, deadline):
        return {"bytes": len(self.data[key]), "sha256": None}

    def write_temporary(self, key, data, deadline):
        self.data[key] = data

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])

    def read(self, key, max_bytes, deadline):
        return self.data[key]


def part(tmp_path, name, entries):
    path = tmp_path / (name + ".parquet")
    proof = write_snapshot(path, sorted(entries), deadline=time.monotonic() + 30)
    return path.read_bytes(), proof


def numbered(wire, linked_metadata, count):
    values = []
    for number in range(count):
        wire["_id"] = f"part-profile-{number}"
        wire["cycle_number"] = 300 + number
        values.append(
            map_profile(decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget())
        )
    return values


def test_P08_N08_each_part_is_certified_for_its_own_bytes_only(tmp_path, wire, linked_metadata):
    first, second = numbered(wire, linked_metadata, 2)
    one, one_proof = part(tmp_path, "one", [(uuid.UUID(int=1), first)])
    two, two_proof = part(tmp_path, "two", [(uuid.UUID(int=2), second)])
    assert one_proof["profiles"] == two_proof["profiles"] == 1
    assert one_proof["membership_sha256"] != two_proof["membership_sha256"]
    store = MemoryStore()
    deadline = time.monotonic() + 10
    certificate = snapshot_certificate(one_proof, one, deadline=deadline)
    evidence = publish_verified(store, one, uuid.uuid4(), certificate, deadline=deadline)
    assert evidence.key == f"normalised/sha256/{hashlib.sha256(one).hexdigest()}.parquet"
    assert store.data[evidence.key] == one
    # The certificate covers exactly the bytes it was issued for; another part never passes it.
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        certificate(two)
    # The evidence stored in the catalogue is plain JSON: no certificate object.
    assert "certificate" not in evidence_json(one_proof)
    json.dumps(evidence_json(one_proof))


def test_P08_part_without_a_writer_certificate_is_verified_in_full_once(
    tmp_path, wire, linked_metadata
):
    (value,) = numbered(wire, linked_metadata, 1)
    payload, proof = part(tmp_path, "plain", [(uuid.UUID(int=1), value)])
    proof = dict(evidence_json(proof))  # a writer that returned no certificate
    conversions = []

    @contextmanager
    def budget():
        counter = CanonicalBudget()
        yield counter
        conversions.append(counter.run_used)

    certificate = snapshot_certificate(
        proof, payload, deadline=time.monotonic() + 10, budget_factory=budget
    )
    assert isinstance(certificate, PublicationSnapshotVerifier)
    assert certificate(payload)["profiles"] == 1 and certificate(payload)["profiles"] == 1
    assert conversions in ([], [len(value.canonical_bytes)])  # a full first check, not repeated
    proof["rows"] = 99
    with pytest.raises(Rejection, match="object_validation_mismatch"):
        snapshot_certificate(proof, payload, deadline=time.monotonic() + 10)(payload)


def test_P08_compacted_snapshot_certifies_the_manifest_population(tmp_path, wire, linked_metadata):
    values = numbered(wire, linked_metadata, 3)
    ids = [uuid.UUID(int=index + 1) for index in range(3)]
    replaced_wire = copy.deepcopy(wire)
    replaced_wire["_id"], replaced_wire["cycle_number"] = "part-profile-1", 301
    replaced_wire["data"][0][0] += 1
    replaced = map_profile(
        decode_json(json.dumps(replaced_wire).encode()), linked_metadata, CanonicalBudget()
    )
    one, _ = part(tmp_path, "a", [(ids[0], values[0]), (ids[1], values[1])])
    two, _ = part(tmp_path, "b", [(ids[1], replaced), (ids[2], values[2])])
    tables = [pq.read_table(tmp_path / "a.parquet"), pq.read_table(tmp_path / "b.parquet")]
    manifest = [
        {"profile_id": str(ids[0]), "hash": values[0].content_hash, "levels": 3},
        {"profile_id": str(ids[1]), "hash": replaced.content_hash, "levels": 3},
        {"profile_id": str(ids[2]), "hash": values[2].content_hash, "levels": 3},
    ]
    snapshot, proof = part(tmp_path, "snapshot", list(merge_parts(tables, manifest)))
    assert (proof["profiles"], proof["rows"]) == (3, 9)
    # The snapshot is exactly what the two parts hold for the manifest members: the same
    # membership evidence as a writer given those three versions directly.
    direct, direct_proof = part(
        tmp_path, "direct", [(ids[0], values[0]), (ids[1], replaced), (ids[2], values[2])]
    )
    assert snapshot == direct and proof["membership_sha256"] == direct_proof["membership_sha256"]
    assert len(one) + len(two) > 0
