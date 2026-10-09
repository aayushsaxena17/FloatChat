"""Disposable-container probe invoked by the offline integration test only."""

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.objects import publish_verified
from floatchat_core.ingestion.parquet import verify_snapshot, write_snapshot


def main():
    store = MinioStore(
        "http://127.0.0.1:9000",
        "floatchat-offline-test",
        os.environ["MINIO_ROOT_USER"],
        os.environ["MINIO_ROOT_PASSWORD"],
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            store.client.list_buckets()
            break
        except (ClientError, BotoCoreError):
            assert time.monotonic() < deadline, "Disposable object store startup timed out"
            time.sleep(0.25)
    store.client.create_bucket(Bucket=store.bucket)
    examples = Path("/test/tests/fixtures/argovis/examples")
    wire = json.loads((examples / "published_inventory_profile.json").read_text())[0]
    arrays = json.loads((examples / "published_temperature_pressure_arrays.json").read_text())
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    wire["geolocation"]["coordinates"] = [70, 10]
    wire["data_info"] = json.loads((examples / "published_data_info.json").read_text())
    wire["data"] = [row[:3] for row in arrays]
    metadata = {
        row["_id"]: row for row in decode_json((examples / "published_metadata.json").read_bytes())
    }
    profile = map_profile(decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget())
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "science.parquet"
        write_snapshot(path, {uuid.uuid4(): profile}, deadline=time.monotonic() + 10)
        data = path.read_bytes()

        def validate(value):
            return verify_snapshot(io.BytesIO(value), deadline=time.monotonic() + 10)

        first = publish_verified(
            store, data, uuid.uuid4(), validate, deadline=time.monotonic() + 30
        )
        second = publish_verified(
            store, data, uuid.uuid4(), validate, deadline=time.monotonic() + 30
        )
        assert first.key == second.key and first.sha256 == second.sha256
        assert store.read(first.key, len(data), time.monotonic() + 10) == data
        assert first.validation["rows"] == 3 and first.validation["profiles"] == 1
        # Live confirmation of the pinned server's behaviour: PutObject accepted the
        # SHA-256 parameters (no fallback) and HEAD reports the stored checksum.
        assert store.checksums, "MinIO refused the SHA-256 PutObject parameters; fallback in use"
        stat = store.stat(first.key, time.monotonic() + 10)
        assert stat == {"bytes": len(data), "sha256": first.sha256}, stat
        audited = publish_verified(
            store, data, uuid.uuid4(), validate, deadline=time.monotonic() + 30, audit=True
        )
        assert audited.key == first.key
        # The server, not the client, verifies the checksum: a wrong digest is refused and
        # nothing is stored. The raw error code is reported for the CHECKSUM_MISMATCH set.
        other = b"checksum-probe-payload"
        key = f"raw/sha256/{hashlib.sha256(other).hexdigest()}.json"
        wrong = base64.b64encode(hashlib.sha256(b"not the payload").digest()).decode()
        try:
            store.client.put_object(
                Bucket=store.bucket,
                Key=key,
                Body=other,
                IfNoneMatch="*",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=wrong,
            )
        except ClientError as error:
            print("wrong-checksum-error-code", error.response["Error"]["Code"], file=sys.stderr)
        else:
            raise AssertionError("MinIO stored an object whose SHA-256 did not match")
        try:
            store.write_immutable(
                key, other, hashlib.sha256(b"not the payload").hexdigest(), time.monotonic() + 10
            )
        except Rejection as error:
            assert str(error) == "object_checksum_mismatch", error
        else:
            raise AssertionError("write_immutable accepted a wrong SHA-256")
        assert store.checksums, "A real mismatch must not switch the store to the fallback"
        try:
            store.stat(key, time.monotonic() + 10)
        except Rejection as error:
            assert str(error) == "object_missing", error
        else:
            raise AssertionError("A refused checksum write left an object behind")
        net = publish_verified(
            store,
            other,
            uuid.uuid4(),
            lambda value: {"bytes": len(value)},
            deadline=time.monotonic() + 30,
            raw="nc",
        )
        assert net.key == f"raw/sha256/{hashlib.sha256(other).hexdigest()}.nc"
        # Same-length bytes under an existing key (stored without a SHA-256 checksum) are
        # found by the read-back on the collision path, never overwritten.
        squatter = b"squatter-same-length-payload"
        squat_key = f"raw/sha256/{hashlib.sha256(squatter).hexdigest()}.json"
        store.client.put_object(Bucket=store.bucket, Key=squat_key, Body=b"X" * len(squatter))
        try:
            publish_verified(
                store,
                squatter,
                uuid.uuid4(),
                lambda value: {"bytes": len(value)},
                deadline=time.monotonic() + 30,
                raw=True,
            )
        except ValueError as error:
            assert str(error) == "object_checksum_mismatch"
        else:
            raise AssertionError("Same-length corrupt object was accepted")
        assert store.read(squat_key, 1024, time.monotonic() + 10) == b"X" * len(squatter)
        store.client.put_object(Bucket=store.bucket, Key=first.key, Body=b"corrupt-test-object")
        # Conditional final publication preserves an existing corrupt key and
        # the byte count from stat rejects it, never an overwrite repair.
        try:
            publish_verified(store, data, uuid.uuid4(), validate, deadline=time.monotonic() + 30)
        except ValueError as error:
            assert str(error) == "object_checksum_mismatch"
        else:
            raise AssertionError("Corrupt immutable object was silently overwritten")
    print("offline-minio-publication-verified")


if __name__ == "__main__":
    main()
