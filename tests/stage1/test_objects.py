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
        self.corrupt = None

    def write_temporary(self, key, data, deadline):
        assert deadline > time.monotonic()
        validate_key(key)
        self.operations.append("temporary")
        self.data[key] = data

    def read(self, key, max_bytes, deadline):
        assert deadline > time.monotonic()
        validate_key(key)
        self.operations.append("read_temp" if key.startswith("tmp/") else "read_final")
        if key not in self.data:
            raise Rejection("object_missing")
        result = self.data[key] + (
            b"corrupt" if self.corrupt and key.startswith(self.corrupt) else b""
        )
        if len(result) > max_bytes:
            raise Rejection("object_size_limit")
        return result

    def publish_if_absent(self, temporary, final, deadline):
        assert deadline > time.monotonic()
        validate_key(temporary)
        validate_key(final)
        self.operations.append("publish")
        self.data.setdefault(final, self.data[temporary])


def validate(data):
    if data != b"scientific-fixture":
        raise Rejection("invalid_schema")
    return {"levels": 2, "profiles": 1, "schema": "test-v1"}


def test_P01_verified_temporary_and_final_order():
    store = MemoryStore()
    evidence = publish_verified(
        store, b"scientific-fixture", uuid.uuid4(), validate, deadline=time.monotonic() + 5
    )
    assert store.operations == ["temporary", "read_temp", "publish", "read_final"]
    assert evidence.sha256 == hashlib.sha256(b"scientific-fixture").hexdigest()
    assert evidence.key == f"normalised/sha256/{evidence.sha256}.parquet"
    assert evidence.validation == {"levels": 2, "profiles": 1, "schema": "test-v1"}


@pytest.mark.parametrize("phase", ["tmp/", "normalised/"])
def test_P02_corrupt_bytes_fail_before_catalogue(phase):
    store = MemoryStore()
    store.corrupt = phase
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        publish_verified(
            store, b"scientific-fixture", uuid.uuid4(), validate, deadline=time.monotonic() + 5
        )


def test_P02_immutable_existing_key_not_overwritten():
    store = MemoryStore()
    digest = hashlib.sha256(b"scientific-fixture").hexdigest()
    final = f"normalised/sha256/{digest}.parquet"
    store.data[final] = b"different-existing-bytes"
    with pytest.raises(Rejection):
        publish_verified(
            store, b"scientific-fixture", uuid.uuid4(), validate, deadline=time.monotonic() + 5
        )
    assert store.data[final] == b"different-existing-bytes"


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
    ],
)
def test_B08_generated_object_keys_only(key):
    with pytest.raises(Rejection, match="invalid_object_key"):
        validate_key(key)
