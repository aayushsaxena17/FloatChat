"""Disposable-container probe invoked by the offline integration test only."""

import io
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
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
        store.client.put_object(Bucket=store.bucket, Key=first.key, Body=b"corrupt-test-object")
        # Conditional final publication preserves an existing corrupt key and
        # post-publication read-back rejects it, never an overwrite repair.
        try:
            publish_verified(store, data, uuid.uuid4(), validate, deadline=time.monotonic() + 30)
        except ValueError as error:
            assert str(error) == "object_checksum_mismatch"
        else:
            raise AssertionError("Corrupt immutable object was silently overwritten")
    print("offline-minio-publication-verified")


if __name__ == "__main__":
    main()
