"""Offline PostgreSQL/MinIO probe: a GDAC run over the committed fixtures, end to end.

One chunk (tile 70:-30, UTC day 2025-01-15) of tests/fixtures/gdac is admitted as a gdac run
(prepare_cache over a pre-populated copy, so nothing is downloaded), landed by GdacSource,
mapped by gdac_map_profile and published through commit_publication. Network-isolated.
"""

import gzip
import hashlib
import io
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from floatchat_core.ingestion import gdac
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.parquet import verify_snapshot
from floatchat_core.ingestion.planning import Interval, Tile, timestamp
from floatchat_core.ingestion.reporting import persisted_report
from floatchat_core.ingestion.repository import Repository
from floatchat_workers.ingestion import process_ticket
from psycopg.types.json import Jsonb

ENV = uuid.UUID("00000000-0000-4000-8000-000000000003")
DAY = Interval(timestamp("2025-01-15T00:00:00Z"), timestamp("2025-01-16T00:00:00Z"))
TILE = Tile(70, -30)
SLOT = "gdac/core/2025-01/70:-30/indian-ocean-v1/gdac-core-v1/scientific-json-v2"
FIXTURES = Path("/test/tests/fixtures/gdac")


def main():
    repository = Repository(os.environ["INGESTION_DATABASE_URL"])
    store = MinioStore(
        "http://127.0.0.1:9000",
        "floatchat-processor-test",
        os.environ["MINIO_ROOT_USER"],
        os.environ["MINIO_ROOT_PASSWORD"],
    )
    ready = time.monotonic() + 30
    while True:
        try:
            store.client.list_buckets()
            break
        except (ClientError, BotoCoreError):
            assert time.monotonic() < ready
            time.sleep(0.25)
    store.client.create_bucket(Bucket=store.bucket)
    repository.connection.execute(
        "INSERT INTO app.ingestion_environment VALUES(%s,'component','acceptance',true,"
        "'floatchat-processor-test','component','component')",
        (ENV,),
    )
    repository.connection.execute("CREATE ROLE component_ingestion LOGIN INHERIT")
    repository.connection.execute("GRANT floatchat_ingestor TO component_ingestion")
    os.environ.update(
        INGESTION_DATABASE_URL="postgresql://component_ingestion@127.0.0.1/gdac_probe",
        INGESTION_ENVIRONMENT_ID=str(ENV),
        INGESTION_BUCKET=store.bucket,
        INGESTION_QUEUE_NAMESPACE="component",
        COMPOSE_PROJECT_NAME="component",
        OBJECT_STORAGE_ENDPOINT="http://127.0.0.1:9000",
        OBJECT_STORAGE_ACCESS_KEY=os.environ["MINIO_ROOT_USER"],
        OBJECT_STORAGE_SECRET_KEY=os.environ["MINIO_ROOT_PASSWORD"],
        INGESTION_APPLICATION_COMMIT="offline-gdac",
    )
    # The key is never needed: a gdac run must not load it.
    os.environ.pop("ARGOVIS_API_KEY", None)
    repository.connection.execute("SET ROLE floatchat_ingestor")
    expected = list(gdac.profiles_from_netcdf(FIXTURES / "20250115_prof.nc", TILE, DAY))
    assert len(expected) == 3

    def execute(cache):
        # prepare_cache over a filled cache: no fetch is possible (no network) and none is made.
        descriptor = gdac.prepare_cache(cache, DAY, time.monotonic() + 60)
        admitted = repository.admit(
            ENV,
            uuid.uuid4(),
            "acceptance",
            DAY,
            {"execution_seconds": 600},
            input_kind="gdac",
            descriptor=descriptor,
        )
        run = uuid.UUID(admitted["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        assert epoch == 1
        stored = repository.run(run)["policy_versions"]
        assert stored == gdac.VERSIONS, stored
        assert repository.input(run)["kind"] == "gdac"
        chunk = uuid.uuid4()
        with repository.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
        repository.connection.execute("RESET ROLE")
        repository.connection.execute(
            "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
            "requested_end,tile,plan_version) VALUES(%s,%s,'component',%s,%s,%s,'component')",
            (
                chunk,
                run,
                DAY.start,
                DAY.end,
                Jsonb({"west": TILE.west, "south": TILE.south, "width": 10, "height": 10}),
            ),
        )
        repository.connection.execute("SET ROLE floatchat_ingestor")
        authority = repository.claim(run, chunk, epoch)
        assert authority is not None
        ticket = repository.ticket(authority)
        result = process_ticket(str(run), str(chunk), str(ticket), "execute")
        assert process_ticket(str(run), str(chunk), str(ticket), "execute") == result
        assert repository.finalize(run) == result
        return run, persisted_report(repository, run)

    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory) / "cache"
        cache.mkdir()
        shutil.copy(FIXTURES / "20250115_prof.nc", cache)
        index = gzip.compress((FIXTURES / "ar_index_indian_2025q1.txt").read_bytes())
        (cache / gdac.INDEX_KEY).write_bytes(index)
        run, first = execute(cache)
        assert first["state"] == "complete", first
        assert first["after_at_report_snapshot"]["measurement_levels"] == sum(
            len(gdac.gdac_map_profile(doc, _budget()).levels) for doc in expected
        )
        metrics = first["persisted_metrics"]
        assert metrics["source_attribution"]["input_kind"] == "gdac"
        assert metrics["policy_versions"] == gdac.VERSIONS
        provenance = metrics["verified_raw_provenance"]
        assert {item["origin"] for item in provenance} == {"gdac"}
        assert {item["role"] for item in provenance} == {
            "inventory_before",
            "profile",
            "inventory_after",
            "metadata",
        }
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute("SELECT DISTINCT source,mapping_version FROM app.argo_profile")
            assert [tuple(row.values()) for row in cursor.fetchall()] == [("gdac", "gdac-core-v1")]
            cursor.execute("SELECT count(*) AS n FROM app.argo_profile")
            assert cursor.fetchone()["n"] == len(expected)
            cursor.execute("SELECT source FROM app.argo_float")
            assert {row["source"] for row in cursor.fetchall()} == {"gdac"}
            cursor.execute(
                "SELECT logical_key,object_key,sha256,bytes,profile_count "
                "FROM app.committed_active_partitions"
            )
            (part,) = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT DISTINCT logical_key FROM app.coverage_receipt")
            assert [row["logical_key"] for row in cursor.fetchall()] == [SLOT]
            cursor.execute("SELECT app.audit_slot_manifest(%s,%s) AS ok", (ENV, SLOT))
            assert cursor.fetchone()["ok"] is True
        assert part["logical_key"] == SLOT and part["profile_count"] == len(expected)
        payload = store.read(part["object_key"], part["bytes"], time.monotonic() + 10)
        assert hashlib.sha256(payload).hexdigest() == part["sha256"]
        assert verify_snapshot(io.BytesIO(payload), deadline=time.monotonic() + 10)["profiles"] == 3
        # The raw NetCDF day is preserved once, content-addressed.
        raw_nc = (FIXTURES / "20250115_prof.nc").read_bytes()
        key = f"raw/sha256/{hashlib.sha256(raw_nc).hexdigest()}.nc"
        assert store.read(key, len(raw_nc), time.monotonic() + 30) == raw_nc
        # A second run over the same cache changes nothing scientifically.
        again_run, again = execute(cache)
        assert again["state"] == "complete" and again["scientific_no_change"], again
        # The slot maintenance paths accept gdac keys.
        assert repository.compactable_slots(ENV, min_parts=1) == [SLOT]
        assert repository.compact(ENV, SLOT, store, time.monotonic() + 60) == "compacted"
        snapshot = repository.catalogue_snapshot(ENV, DAY, tiles=(TILE,), source="gdac")
        assert [record.logical_key for record in snapshot.records] == [SLOT]
        assert snapshot.current_slot_versions[SLOT] >= 1
    repository.close()
    print("offline-gdac-processor-verified")


def _budget():
    from floatchat_core.ingestion.numeric import CanonicalBudget

    return CanonicalBudget()


if __name__ == "__main__":
    main()
