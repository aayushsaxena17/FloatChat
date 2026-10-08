"""Combined restricted PostgreSQL/real MinIO probe, entirely network-isolated.

Synthetic published-example derivatives exercise one explicit component chunk;
they do not claim complete regional or live acceptance coverage.
"""

import hashlib
import io
import json
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from floatchat_core.ingestion.argovis import policy_versions, request_parameters
from floatchat_core.ingestion.landing import logical_request
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.parquet import verify_snapshot
from floatchat_core.ingestion.planning import Interval, PlannedChunk, Tile, timestamp
from floatchat_core.ingestion.reporting import markdown_report, persisted_report
from floatchat_core.ingestion.repository import Repository
from floatchat_workers.ingestion import process_ticket
from psycopg.types.json import Jsonb

ENV = uuid.UUID("00000000-0000-4000-8000-000000000003")
PIECE = PlannedChunk(
    Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-01-07T00:00:00Z")), Tile(70, 10)
)


def main():
    repository = Repository(os.environ["INGESTION_DATABASE_URL"])
    budget = Repository(os.environ["INGESTION_DATABASE_URL"])
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
        INGESTION_DATABASE_URL="postgresql://component_ingestion@127.0.0.1/processor_probe",
        INGESTION_ENVIRONMENT_ID=str(ENV),
        INGESTION_BUCKET=store.bucket,
        INGESTION_QUEUE_NAMESPACE="component",
        COMPOSE_PROJECT_NAME="component",
        INGESTION_REDIS_URL="redis://127.0.0.1:6379/11",
        OBJECT_STORAGE_ENDPOINT="http://127.0.0.1:9000",
        OBJECT_STORAGE_ACCESS_KEY=os.environ["MINIO_ROOT_USER"],
        OBJECT_STORAGE_SECRET_KEY=os.environ["MINIO_ROOT_PASSWORD"],
        INGESTION_APPLICATION_COMMIT="offline-component",
    )
    repository.connection.execute("SET ROLE floatchat_ingestor")
    budget.connection.execute("SET ROLE floatchat_ingestor")
    examples = Path("/test/tests/fixtures/argovis/examples")
    wire = json.loads((examples / "published_inventory_profile.json").read_text())[0]
    arrays = json.loads((examples / "published_temperature_pressure_arrays.json").read_text())
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    wire["geolocation"]["coordinates"] = [70, 10]
    wire["data_info"] = json.loads((examples / "published_data_info.json").read_text())
    wire["data"] = [row[:3] for row in arrays]
    meta = json.loads((examples / "published_metadata.json").read_text())

    def execute(raw, root, statuses=None):
        root.mkdir()
        responses = []
        for role in ("inventory_before", "profile", "inventory_after"):
            data = json.dumps(raw).encode()
            file = root / (role + ".json")
            file.write_bytes(data)
            responses.append(
                {
                    "role": role,
                    "path": "/argo",
                    "parameters": request_parameters(PIECE, inventory=role != "profile"),
                    "file": file.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    "http_status": (statuses or {}).get(role, 200),
                }
            )
        for document in meta:
            file = root / (uuid.uuid4().hex + ".json")
            data = json.dumps([document]).encode()
            file.write_bytes(data)
            responses.append(
                {
                    "role": "metadata",
                    "path": "/argo/meta",
                    "parameters": {"id": document["_id"]},
                    "file": file.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "retrieved_at_utc": datetime.now(UTC).isoformat(),
                }
            )
        index = root / "index.json"
        index.write_text(
            json.dumps(
                {
                    "kind": "synthetic_offline_chunk_fixture",
                    "versions": policy_versions(),
                    "responses": responses,
                }
            )
        )
        descriptor = {
            "fixture_index": str(index),
            "fixture_root": str(root),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        }
        admitted = repository.admit(
            ENV,
            uuid.uuid4(),
            "acceptance",
            PIECE.interval,
            {"execution_seconds": 600},
            input_kind="captured",
            descriptor=descriptor,
        )
        run = uuid.UUID(admitted["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        assert epoch == 1
        # This component chunk is seeded explicitly; full initial plan validation
        # is separately tested. Never describe it as complete regional coverage.
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
                PIECE.interval.start,
                PIECE.interval.end,
                Jsonb({"west": 70, "south": 10, "width": 10, "height": 10}),
            ),
        )
        repository.connection.execute("SET ROLE floatchat_ingestor")
        authority = repository.claim(run, chunk, epoch)
        assert authority is not None
        ticket = repository.ticket(authority)
        result = process_ticket(str(run), str(chunk), str(ticket))
        assert process_ticket(str(run), str(chunk), str(ticket)) == result
        state = repository.finalize(run)
        assert result == state
        return persisted_report(repository, run)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = execute([wire], root / "first")
        assert first["state"] == "complete", first
        assert first["after_at_report_snapshot"]["measurement_levels"] == 3
        assert first["full_snapshot_balanced"] and first["run_eligible_balanced"]
        assert first["payload_accounting"][0]["origin"] == "captured"
        metrics = first["persisted_metrics"]
        assert metrics["run_timing"]["elapsed_seconds"] > 0
        assert metrics["phase_timings"] and metrics["attempt_timing"]
        assert metrics["http_retries"] == 0 and metrics["processing_recoveries"] == 0
        assert metrics["source_attribution"]["input_kind"] == "captured"
        assert metrics["availability"]["full_retained"]["pressure"]["_adjusted"] == 3
        assert first["scientific_level_delta_balanced"]
        assert not first["coverage"]["proved_complete"] and first["coverage"]["gaps"]
        assert first["occurrence_ledger_reconciliation"]["reported_received_profiles"] == 1
        assert first["occurrence_ledger_reconciliation"]["ledger_known_source_levels"] == 3
        provenance = metrics["verified_raw_provenance"]
        assert {item["role"] for item in provenance} == {
            "inventory_before",
            "profile",
            "inventory_after",
            "metadata",
        }
        assert all(item["request_parameters"] and item["sha256"] for item in provenance)
        assert all(
            item["logical_request_sha256"]
            == logical_request(item["endpoint_path"], item["request_parameters"], item["role"])
            for item in provenance
        )
        assert all(
            item["sanitization"]["input_kind"] == "synthetic_offline_chunk_fixture"
            for item in provenance
        )
        options = metrics["active_generations"][0]["verification_evidence"]
        assert options["writer_options"]["compression_level"] == 3
        assert options["storage_comparison"]["index_included"] is True
        assert options["storage_comparison"]["pandas_deep_memory_bytes"] > 0
        frozen_markdown = markdown_report(first)
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute("SELECT object_key,sha256,bytes FROM app.committed_active_partitions")
            generation = cursor.fetchone()
        payload = store.read(generation["object_key"], generation["bytes"], time.monotonic() + 10)
        assert hashlib.sha256(payload).hexdigest() == generation["sha256"]
        assert verify_snapshot(io.BytesIO(payload), deadline=time.monotonic() + 10)["rows"] == 3
        replay = execute([wire], root / "replay")
        assert replay["state"] == "complete" and replay["scientific_no_change"]
        assert replay["active_partition_no_change"]
        assert replay["after_at_report_snapshot"]["attempts"] > replay["before"]["attempts"]
        assert replay["persisted_metrics"]["replacement_levels"]["no_op_levels"] == 3
        assert replay["scientific_level_delta_balanced"]
        empty = execute([], root / "empty")
        assert empty["state"] == "complete" and empty["scientific_no_change"]
        assert empty["active_partition_no_change"]
        assert empty["source_policy"]["empty_delivery_receipts_by_role"] == {}
        # S1-SOURCE-2 receipt: a coherent 404 [] triple is a verified empty delivery.
        roles = ("inventory_before", "profile", "inventory_after")
        empty_404 = execute([], root / "empty_404", dict.fromkeys(roles, 404))
        assert empty_404["state"] == "complete", empty_404
        assert empty_404["scientific_no_change"] and empty_404["active_partition_no_change"]
        assert empty_404["source_policy"]["empty_delivery_receipts_by_role"] == dict.fromkeys(
            roles, 1
        )
        # A mixed 200/404 triple is never an empty delivery.
        mixed = execute([], root / "mixed_404", {"inventory_before": 404})
        assert mixed["state"] != "complete", mixed
        assert mixed["scientific_no_change"] and mixed["active_partition_no_change"]
        # degenerate_levels alone: whole-profile exclusion, never published.
        degenerate = execute([{**wire, "data_warning": ["degenerate_levels"]}], root / "degenerate")
        assert degenerate["state"] == "complete", degenerate
        assert degenerate["scientific_no_change"] and degenerate["active_partition_no_change"]
        policy = degenerate["source_policy"]
        assert policy["source_exclusion_count"] == 1
        assert policy["acceptance_qualification"] == "acceptance_qualified_with_source_exclusions"
        assert policy["scientific_source_complete"] is False
        exclusion = policy["source_exclusions"][0]
        assert exclusion["returned_levels"] == 3 and exclusion["lost_levels"] == "unknown"
        assert exclusion["warning"] == "degenerate_levels" and exclusion["raw_profile_landing"]
        # Any other or additional warning keeps the strict whole-chunk quarantine.
        warned = execute(
            [{**wire, "data_warning": ["degenerate_levels", "unknown_warning"]}], root / "warned"
        )
        assert warned["state"] == "quarantined", warned
        assert warned["source_policy"]["source_exclusion_count"] == 0
        wire["data"] = [row[:2] for row in wire["data"]]
        wire["source"][0]["date_updated"] = "2025-02-01T00:00:00Z"
        newer = execute([wire], root / "newer")
        assert newer["state"] == "complete", newer
        assert newer["after_at_report_snapshot"]["measurement_levels"] == 2
        assert newer["full_snapshot_balanced"] and newer["run_eligible_balanced"]
        assert newer["persisted_metrics"]["replacement_levels"]["old_levels_removed"] == 3
        assert newer["persisted_metrics"]["replacement_levels"]["inserted_replacement_levels"] == 2
        assert newer["scientific_level_delta_balanced"]
        assert persisted_report(repository, uuid.UUID(first["run_id"])) == first
        assert (
            markdown_report(persisted_report(repository, uuid.UUID(first["run_id"])))
            == frozen_markdown
        )
        assert not newer["active_partition_no_change"]
        wire["data"][0][0] += 1
        conflict = execute([wire], root / "conflict")
        assert conflict["state"] == "quarantined", conflict
        assert conflict["scientific_no_change"] and conflict["active_partition_no_change"]
        assert all(row["received_bytes"] == 0 for row in conflict["payload_accounting"])
        assert any(
            item["reason"] == "revision_conflict"
            for item in conflict["persisted_metrics"]["state_reasons"]
        )
        assert conflict["scientific_level_delta_balanced"]
    budget.close()
    from capacity_probe import verify_capacity

    capacity_evidence = verify_capacity(repository, ENV)
    from request_owner_probe import verify_http_path

    http_evidence = verify_http_path(repository, store, ENV, PIECE)
    from split_replay_probe import verify_split_replay

    with tempfile.TemporaryDirectory() as directory:
        replay_evidence = verify_split_replay(
            repository, ENV, wire, meta, Path(directory) / "split"
        )
    print(
        json.dumps(
            {
                "http_request_owner": http_evidence,
                "split_replay": replay_evidence,
                "publication_capacity": capacity_evidence,
            }
        )
    )
    repository.close()
    print("offline-combined-processor-verified")


if __name__ == "__main__":
    main()
