"""Publication protocol component tests, not a PostgreSQL merge acceptance claim."""

import hashlib
import time
import uuid
from dataclasses import replace

import pytest
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.objects import (
    CatalogueRecord,
    CatalogueSnapshot,
    publish_verified,
    select_active_partitions,
    validate_key,
)


class MemoryStore:
    def __init__(self):
        self.data = {}
        self.operations = []
        self.corrupt = None  # read-back of keys with this prefix returns extra bytes
        self.stat_bytes = None  # stat reports this byte count instead of the stored one
        self.stat_sha = None  # stat reports this checksum instead of the stored one
        self.checksums = True  # False: the store keeps no checksum (stat reports None)
        self.verify_existing = True  # False: an existing key is left alone without comparing

    def write_immutable(self, key, data, sha256_hex, deadline):
        assert deadline > time.monotonic()
        validate_key(key)
        assert not key.startswith("tmp/")
        assert hashlib.sha256(data).hexdigest() == sha256_hex  # what the server would verify
        self.operations.append("write_immutable")
        if key in self.data:
            if self.verify_existing and self.data[key] != data:
                raise Rejection("object_checksum_mismatch")
            return
        self.data[key] = data

    def stat(self, key, deadline):
        assert deadline > time.monotonic()
        validate_key(key)
        self.operations.append("stat")
        if key not in self.data:
            raise Rejection("object_missing")
        stored = self.data[key]
        digest = hashlib.sha256(stored).hexdigest() if self.checksums else None
        return {
            "bytes": len(stored) if self.stat_bytes is None else self.stat_bytes,
            "sha256": digest if self.stat_sha is None else self.stat_sha,
        }

    def read(self, key, max_bytes, deadline):
        assert deadline > time.monotonic()
        validate_key(key)
        self.operations.append("read")
        if key not in self.data:
            raise Rejection("object_missing")
        result = self.data[key] + (
            b"corrupt" if self.corrupt and key.startswith(self.corrupt) else b""
        )
        if len(result) > max_bytes:
            raise Rejection("object_size_limit")
        return result

    def write_temporary(self, key, data, deadline):
        raise AssertionError("publication no longer uploads a temporary object")

    def publish_if_absent(self, temporary, final, deadline):
        raise AssertionError("publication no longer copies a temporary object")


class Validator:
    def __init__(self):
        self.calls = 0

    def __call__(self, data):
        self.calls += 1
        return validate(data)


def validate(data):
    if data != b"scientific-fixture":
        raise Rejection("invalid_schema")
    return {"levels": 2, "profiles": 1, "schema": "test-v1"}


def publish(store, **options):
    return publish_verified(
        store,
        b"scientific-fixture",
        options.pop("publication", uuid.uuid4()),
        options.pop("validate", validate),
        deadline=time.monotonic() + 5,
        **options,
    )


def test_P01_single_conditional_put_then_stat():
    store = MemoryStore()
    check = Validator()
    evidence = publish(store, validate=check)
    assert store.operations == ["write_immutable", "stat"]
    assert check.calls == 1
    assert evidence.sha256 == hashlib.sha256(b"scientific-fixture").hexdigest()
    assert evidence.key == f"normalised/sha256/{evidence.sha256}.parquet"
    assert evidence.byte_count == len(b"scientific-fixture")
    assert evidence.validation == {"levels": 2, "profiles": 1, "schema": "test-v1"}
    assert evidence.temporary_key is None
    assert list(store.data) == [evidence.key]


def test_P01_reserved_temporary_key_is_checked_and_never_written():
    store = MemoryStore()
    publication = uuid.uuid4()
    reserved = f"tmp/{publication.hex}/{uuid.uuid4().hex}"
    evidence = publish(store, publication=publication, temporary_key=reserved)
    assert evidence.temporary_key == reserved
    assert reserved not in store.data
    for wrong in (f"tmp/{uuid.uuid4().hex}/{uuid.uuid4().hex}", "tmp/not-a-key"):
        with pytest.raises(Rejection, match="invalid_temporary_key"):
            publish(store, publication=publication, temporary_key=wrong)


def test_P01_invalid_bytes_and_budgets_never_reach_the_store():
    store = MemoryStore()
    with pytest.raises(Rejection, match="invalid_schema"):
        publish_verified(store, b"other", uuid.uuid4(), validate, deadline=time.monotonic() + 5)
    with pytest.raises(Rejection, match="object_size_limit"):
        publish(store, max_bytes=4)
    with pytest.raises(Rejection, match="object_size_limit"):
        publish(store, max_bytes=0)
    with pytest.raises(Rejection, match="object_deadline"):
        publish_verified(
            store, b"scientific-fixture", uuid.uuid4(), validate, deadline=time.monotonic() - 1
        )
    assert not store.operations and not store.data


@pytest.mark.parametrize("field", ["stat_bytes", "stat_sha"])
def test_P02_stat_disagreement_fails_before_catalogue(field):
    store = MemoryStore()
    setattr(store, field, 17 if field == "stat_bytes" else "0" * 64)
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        publish(store)
    assert store.operations == ["write_immutable", "stat"]


def test_P02_stat_without_checksum_accepts_equal_byte_count():
    store = MemoryStore()
    store.checksums = False
    assert publish(store).byte_count == len(b"scientific-fixture")


def test_P02_missing_object_after_write_is_not_published():
    class Forgetful(MemoryStore):
        def write_immutable(self, key, data, sha256_hex, deadline):
            self.operations.append("write_immutable")

    with pytest.raises(Rejection, match="object_missing"):
        publish(Forgetful())


@pytest.mark.parametrize("phase", ["normalised/", "raw/"])
def test_P02_audit_reads_back_and_detects_corrupt_stored_bytes(phase):
    store = MemoryStore()
    store.corrupt = phase
    options = {"raw": True} if phase == "raw/" else {}
    assert publish(store, **options).byte_count  # Without audit the stat is the proof.
    assert store.operations == ["write_immutable", "stat"]
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        publish(store, audit=True, **options)


def test_P02_audit_revalidates_the_stored_bytes():
    store = MemoryStore()
    seen = []

    def validator(data):
        seen.append(data)
        return {"levels": len(seen), "profiles": 1, "schema": "test-v1"}

    with pytest.raises(Rejection, match="object_validation_mismatch"):
        publish(store, validate=validator, audit=True)
    assert store.operations == ["write_immutable", "stat", "read"] and len(seen) == 2
    store = MemoryStore()
    evidence = publish(store, validate=Validator(), audit=True)
    assert store.operations == ["write_immutable", "stat", "read"]
    assert evidence.validation["levels"] == 2


@pytest.mark.parametrize("verify_existing", [True, False])
def test_P02_immutable_existing_key_not_overwritten(verify_existing):
    store = MemoryStore()
    store.verify_existing = verify_existing
    digest = hashlib.sha256(b"scientific-fixture").hexdigest()
    final = f"normalised/sha256/{digest}.parquet"
    store.data[final] = b"different-existing-bytes"
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        publish(store)
    assert store.data[final] == b"different-existing-bytes"


def test_P02_existing_identical_object_is_a_safe_republication():
    store = MemoryStore()
    first, second = publish(store), publish(store)
    assert first == second and len(store.data) == 1


def test_raw_json_and_netcdf_keys():
    store = MemoryStore()
    digest = hashlib.sha256(b"scientific-fixture").hexdigest()
    assert publish(store, raw=True).key == f"raw/sha256/{digest}.json"
    assert publish(store, raw="nc").key == f"raw/sha256/{digest}.nc"
    assert publish(store).key == f"normalised/sha256/{digest}.parquet"
    assert set(store.data) == {
        f"raw/sha256/{digest}.json",
        f"raw/sha256/{digest}.nc",
        f"normalised/sha256/{digest}.parquet",
    }
    with pytest.raises(Rejection, match="invalid_object_key"):
        publish(store, raw="parquet")
    with pytest.raises(Rejection, match="invalid_object_key"):
        publish(store, raw="nc/../x")


def record(environment, payload):
    digest = hashlib.sha256(payload).hexdigest()
    return CatalogueRecord(
        uuid.uuid4(),
        environment,
        "slot",
        1,
        1,
        "active",
        True,
        True,
        "indian-ocean-v1",
        "test-v1",
        f"normalised/sha256/{digest}.parquet",
        digest,
        len(payload),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "superseded"},
        {"status": "pending"},
        {"status": "quarantined"},
        {"committed": False},
        {"verified": False},
        {"geometry_version": "wrong"},
        {"schema_version": "wrong"},
        {"slot_version": 0},
        {"environment_id": uuid.uuid4()},
    ],
)
def test_P06_nonselectable_catalogue(change):
    store = MemoryStore()
    environment = uuid.uuid4()
    good = record(environment, b"fixture")
    store.data[good.key] = b"fixture"
    snapshot = CatalogueSnapshot((replace(good, **change),), {"slot": 1}, ("missing-receipt",))
    result = select_active_partitions(snapshot, store, environment, "indian-ocean-v1", "test-v1")
    assert not result.partitions and result.gaps == ("missing-receipt",)
    assert not store.operations


def test_P10_selector_unavailable_budget_and_no_stale_substitute():
    store = MemoryStore()
    environment = uuid.uuid4()
    good = record(environment, b"fixture")
    snapshot = CatalogueSnapshot((good,), {"slot": 1}, ())
    result = select_active_partitions(snapshot, store, environment, "indian-ocean-v1", "test-v1")
    assert not result.partitions and result.gaps == ("slot:object_unavailable",)
    store.data[good.key] = b"fixture"
    result = select_active_partitions(
        snapshot, store, environment, "indian-ocean-v1", "test-v1", max_read_bytes=1
    )
    assert not result.partitions and result.gaps == ("slot:verification_budget",)
    result = select_active_partitions(snapshot, store, environment, "indian-ocean-v1", "test-v1")
    assert result.partitions == (good,) and not result.gaps


@pytest.mark.parametrize(
    "key",
    [
        "../evil",
        "/raw/evil",
        "raw/sha256/" + "a" * 64 + ".json/evil",
        "tmp/a/b",
        "normalised/sha256/" + "A" * 64 + ".parquet",
        "raw/sha256/" + "a" * 64 + ".nc/evil",
        "raw/sha256/" + "a" * 64 + ".NC",
        "raw/sha256/" + "a" * 63 + ".nc",
        "normalised/sha256/" + "a" * 64 + ".nc",
    ],
)
def test_B08_generated_object_keys_only(key):
    with pytest.raises(Rejection, match="invalid_object_key"):
        validate_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "raw/sha256/" + "a" * 64 + ".json",
        "raw/sha256/" + "a" * 64 + ".nc",
        "normalised/sha256/" + "a" * 64 + ".parquet",
        "tmp/" + "a" * 32 + "/" + "b" * 32,
    ],
)
def test_generated_object_keys_accepted(key):
    validate_key(key)
