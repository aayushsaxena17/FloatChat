"""One-run regional-plan capacity model; all source mutations are synthetic.

Runs only inside a new network-none disposable database/MinIO namespace. The
model cannot establish the population or completeness of the live region.
"""

import copy
import hashlib
import json
import os
import resource
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import BotoCoreError, ClientError
from floatchat_core.ingestion.argovis import policy_versions, request_parameters
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import Interval, plan, timestamp
from floatchat_core.ingestion.processor import Processor
from floatchat_core.ingestion.processor import map_profile as original_map_profile
from floatchat_core.ingestion.reporting import persisted_report
from floatchat_core.ingestion.repository import Repository
from floatchat_workers.ingestion import process_ticket

INCOMING_HASHES = set()


def deny(*args, **kwargs):
    raise AssertionError("upstream_and_credentials_denied")


def operation():
    names = []
    frame = sys._getframe(1)
    for _ in range(18):
        if frame is None:
            break
        names.append((frame.f_code.co_name, Path(frame.f_code.co_filename).name))
        frame = frame.f_back
    if ("map", "processor.py") in names:
        return "incoming_normalization"
    if ("rows", "repository.py") in names:
        return "retained_database_certification"
    if ("old", "processor.py") in names:
        return "incoming_existing_database_comparison"
    if ("restore", "spool.py") in names:
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_name == "restore" and "digest" in frame.f_locals:
                return (
                    "incoming_spool_certification"
                    if frame.f_locals["digest"] in INCOMING_HASHES
                    else "retained_spool_certification"
                )
            frame = frame.f_back
        return "unattributed_spool_certification"
    if ("finish", "parquet.py") in names:
        return (
            "publication_object_readback"
            if ("publish_verified", "objects.py") in names
            else "publication_local_readback"
        )
    if ("lose_once", "regional_capacity_probe.py") in names:
        return "bounded_recovery_reservation"
    return "other_bounded_operation"


def main():
    started = time.monotonic()
    root_source = Path("/test")
    sources = [
        Path(__file__),
        *sorted((root_source / "packages/core/src").rglob("*.py")),
        *sorted((root_source / "workers/src").rglob("*.py")),
        *sorted((root_source / "infra/migrations/versions").glob("*.sql")),
    ]
    source_pins = {
        str(p.relative_to(root_source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
    }
    admin = Repository(os.environ["INGESTION_DATABASE_URL"])
    store = MinioStore(
        "http://127.0.0.1:9000",
        "regional-model",
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
    environment = uuid.uuid4()
    admin.connection.execute(
        "INSERT INTO app.ingestion_environment VALUES(%s,'regional-model','acceptance',true,"
        "'regional-model','regional-model','regional-model')",
        (environment,),
    )
    admin.connection.execute("CREATE ROLE regional_model LOGIN INHERIT")
    admin.connection.execute("GRANT floatchat_ingestor TO regional_model")
    admin.connection.execute(
        "CREATE TABLE public.offline_capacity_operation(work uuid PRIMARY KEY,"
        "operation text NOT NULL)"
    )
    admin.connection.execute(
        "CREATE TABLE public.offline_capacity_profile(source_id text,chunk uuid,hash text,"
        "canonical_bytes bigint,levels integer)"
    )
    os.environ.update(
        INGESTION_DATABASE_URL="postgresql://regional_model@127.0.0.1/regional_model",
        INGESTION_ENVIRONMENT_ID=str(environment),
        INGESTION_BUCKET=store.bucket,
        INGESTION_QUEUE_NAMESPACE="regional-model",
        COMPOSE_PROJECT_NAME="regional-model",
        INGESTION_REDIS_URL="redis://127.0.0.1:6379/11",
        OBJECT_STORAGE_ENDPOINT="http://127.0.0.1:9000",
        OBJECT_STORAGE_ACCESS_KEY=os.environ["MINIO_ROOT_USER"],
        OBJECT_STORAGE_SECRET_KEY=os.environ["MINIO_ROOT_PASSWORD"],
        INGESTION_APPLICATION_COMMIT="offline-regional-model",
    )
    repository = Repository(os.environ["INGESTION_DATABASE_URL"])
    repository.connection.execute("SET ROLE floatchat_ingestor")
    interval = Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-04-01T00:00:00Z"))
    roots = plan(interval)
    assert len(roots) == 270  # plan v2: three monthly roots per tile (ADR-0041)
    basis = Path("/test/tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45")
    profile_bytes = (basis / "02-profile.json").read_bytes()
    metadata_bytes = (basis / "04-metadata.json").read_bytes()
    authentic = json.loads(profile_bytes)[0]
    assert authentic["_id"] == "2904014_040" and len(authentic["data"][0]) == 501
    # Per monthly root; the densest measured Jan-Mar 2025 slot holds 87 profiles.
    weights = {(80, -30): 90, (70, -20): 40, (60, -10): 20}
    original_reserve = Repository.canonical_reserve
    original_publish = Processor.publish
    original_commit = Repository.commit
    worker_loss = rebuild = False
    recoveries = []
    noops = []

    def measured_reserve(self, authority):
        work = original_reserve(self, authority)
        admin.connection.execute(
            "INSERT INTO public.offline_capacity_operation VALUES(%s,%s)", (work, operation())
        )
        return work

    def measured_map(document, metadata, budget):
        value = original_map_profile(document, metadata, budget)
        INCOMING_HASHES.add(value.content_hash)
        authority = sys._getframe(1).f_locals["self"].authority
        admin.connection.execute(
            "INSERT INTO public.offline_capacity_profile VALUES(%s,%s,%s,%s,%s)",
            (
                value.source_profile_id,
                authority.chunk,
                value.content_hash,
                len(value.canonical_bytes),
                len(value.levels),
            ),
        )
        return value

    def lose_once(self):
        nonlocal worker_loss
        if not worker_loss and self.raw_paths["profile"].stat().st_size > 2:
            worker_loss = True
            self.budget_repository.canonical_reserve(self.authority)
            raise Rejection("publication_fenced")
        return original_publish(self)

    def rebuild_once(self, authority, intent, generations, receipts):
        nonlocal rebuild
        if generations and not rebuild:
            rebuild = True
            raise Rejection("publication_base_changed")
        return original_commit(self, authority, intent, generations, receipts)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        responses = []
        expected = incoming = 0
        for ordinal, piece in enumerate(roots):
            count = weights.get((piece.tile.west, piece.tile.south), 0)
            docs = []
            for number in range(count):
                value = copy.deepcopy(authentic)
                shared = piece.tile.west == 80 and piece.interval.start.day == 1 and number < 4
                value["_id"] = (
                    f"synthetic-moving-{number}"
                    if shared
                    else f"synthetic-regional-{ordinal:04d}-{number:02d}"
                )
                value["cycle_number"] = 9000 + (number if shared else ordinal * 40 + number)
                value["timestamp"] = (piece.interval.start + timedelta(hours=12)).isoformat()
                value["geolocation"]["coordinates"] = [piece.tile.west + 5, piece.tile.south + 5]
                for source in value["source"]:
                    source["date_updated"] = (
                        timestamp(source["date_updated"])
                        + timedelta(days=piece.interval.start.month)
                    ).isoformat()
                docs.append(value)
            incoming += count
            expected += count - (
                4
                if count == 90 and piece.interval.start.day == 1 and piece.interval.start.month > 1
                else 0
            )
            data = json.dumps(docs, separators=(",", ":")).encode()
            file = root / (f"{ordinal}.json" if count else "empty.json")
            if not file.exists():
                file.write_bytes(data)
            for role in ("inventory_before", "profile", "inventory_after"):
                responses.append(
                    {
                        "role": role,
                        "path": "/argo",
                        "parameters": request_parameters(piece, inventory=role != "profile"),
                        "file": file.name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    }
                )
        for meta in json.loads(metadata_bytes):
            raw = json.dumps([meta]).encode()
            file = root / ("meta-" + uuid.uuid4().hex + ".json")
            file.write_bytes(raw)
            responses.append(
                {
                    "role": "metadata",
                    "path": "/argo/meta",
                    "parameters": {"id": meta["_id"]},
                    "file": file.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
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
        admitted = repository.admit(
            environment,
            uuid.uuid4(),
            "acceptance",
            interval,
            {"execution_seconds": 21600},
            input_kind="captured",
            descriptor={
                "fixture_index": str(index),
                "fixture_root": str(root),
                "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            },
        )
        run = uuid.UUID(admitted["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        assert epoch is not None
        repository.persist_plan(run, epoch)
        chunks = repository.chunks(run)
        assert len(chunks) == 270
        before_control = repository.run(run)
        progress = []
        # All empty roots are exercised, then the occupied roots in chronological
        # order. This changes dispatch order only, never the stored selection plan.
        ordered = sorted(
            chunks,
            key=lambda c: (
                (c["tile"]["west"], c["tile"]["south"]) in weights,
                c["requested_start"],
                c["tile"]["west"],
                c["tile"]["south"],
            ),
        )
        with (
            patch.object(RequestOwner, "obtain", deny),
            patch("floatchat_workers.ingestion.upstream_credential", deny),
            patch.object(Repository, "canonical_reserve", measured_reserve),
            patch("floatchat_core.ingestion.processor.map_profile", measured_map),
            patch.object(Processor, "publish", lose_once),
            patch.object(Repository, "commit", rebuild_once),
        ):
            for ordinal, chunk in enumerate(ordered):
                INCOMING_HASHES.clear()
                repository.controller_heartbeat(run, epoch)
                authority = repository.claim(run, chunk["id"], epoch)
                assert authority is not None
                ticket = repository.ticket(authority)
                result = process_ticket(str(run), str(chunk["id"]), str(ticket))
                if result == "recovery_required":
                    admin.connection.execute(
                        "UPDATE app.ingestion_chunk SET lease_until="
                        "clock_timestamp()-interval '1 second' WHERE id=%s",
                        (chunk["id"],),
                    )
                    next_authority = repository.claim(run, chunk["id"], epoch)
                    assert next_authority is not None and next_authority.fence > authority.fence
                    next_ticket = repository.ticket(next_authority)
                    result = process_ticket(str(run), str(chunk["id"]), str(next_ticket))
                    recoveries.append(
                        {
                            "chunk": str(chunk["id"]),
                            "old_fence": authority.fence,
                            "new_fence": next_authority.fence,
                            "result": result,
                        }
                    )
                if (
                    ordinal % 90 == 0
                    or chunk["tile"]["west"] in (60, 70, 80)
                    and (chunk["tile"]["west"], chunk["tile"]["south"]) in weights
                ):
                    progress.append(
                        {
                            "processed": ordinal + 1,
                            "state": result,
                            "canonical_bytes": repository.run(run)["canonical_bytes"],
                        }
                    )
                if result != "complete":
                    break
                if (chunk["tile"]["west"], chunk["tile"]["south"]) in weights and len(noops) < 3:
                    before = admin.connection.execute(
                        "SELECT app.scientific_snapshot() AS value"
                    ).fetchone()["value"]
                    spent = repository.run(run)["canonical_bytes"]
                    assert process_ticket(str(run), str(chunk["id"]), str(ticket)) == "complete"
                    after = admin.connection.execute(
                        "SELECT app.scientific_snapshot() AS value"
                    ).fetchone()["value"]
                    assert before == after and spent == repository.run(run)["canonical_bytes"]
                    noops.append(
                        {
                            "chunk": str(chunk["id"]),
                            "kind": "lost_ack_complete_delivery",
                            "science_catalogue_attempt_audit_unchanged": True,
                        }
                    )
        remaining = [
            c
            for c in repository.chunks(run)
            if c["state"] not in ("complete", "failed", "quarantined")
        ]
        state = repository.finalize(run, "execution_failed" if remaining else None)
        report = persisted_report(repository, run)
        after_control = repository.run(run)
        for name in ("work_deadline", "deadline", "run_reference_time_utc", "limits"):
            assert before_control[name] == after_control[name]
        rows = list(
            admin.connection.execute(
                "SELECT o.operation,w.status,count(*) AS operations,sum(w.actual_bytes) AS bytes "
                "FROM app.canonical_work w JOIN app.ingestion_chunk c ON c.id=w.chunk_id "
                "JOIN public.offline_capacity_operation o ON o.work=w.id WHERE c.run_id=%s "
                "GROUP BY o.operation,w.status ORDER BY o.operation,w.status",
                (run,),
            )
        )
        assert sum(int(row["bytes"] or 0) for row in rows) == after_control["canonical_bytes"]
        assert after_control["canonical_bytes"] <= 40 * 1024**3
        assert report["final_evidence_frozen"] and report["full_snapshot_balanced"]
        measurement = admin.connection.execute(
            "SELECT count(*) AS profiles,"
            "sum(octet_length(scientific_content::text)) AS postgres_json_bytes,"
            "sum(level_count) AS levels FROM app.argo_profile"
        ).fetchone()
        sizes = admin.connection.execute(
            "SELECT count(*) AS measured_normalization_occurrences,"
            "count(DISTINCT source_id) AS distinct_source_ids,"
            "min(canonical_bytes) AS minimum_bytes,"
            "max(canonical_bytes) AS maximum_bytes,sum(canonical_bytes) AS total_bytes,"
            "sum(levels) AS levels FROM public.offline_capacity_profile"
        ).fetchone()
        per_publication = list(
            admin.connection.execute(
                "SELECT c.id,c.requested_start,c.requested_end,c.tile,c.state,c.reason,"
                "o.operation,sum(w.actual_bytes) AS bytes,count(*) AS operations "
                "FROM app.ingestion_chunk c JOIN app.canonical_work w ON w.chunk_id=c.id "
                "JOIN public.offline_capacity_operation o ON o.work=w.id WHERE c.run_id=%s "
                "GROUP BY c.id,o.operation ORDER BY c.requested_start,c.id,o.operation",
                (run,),
            )
        )
        output = {
            "kind": "measured_one_run_270_root_plan_v2_synthetic_capacity_model",
            "measured_at_utc": datetime.now(UTC).isoformat(),
            "source_file_sha256": source_pins,
            "source_files_unchanged": all(
                hashlib.sha256((root_source / p).read_bytes()).hexdigest() == sha
                for p, sha in source_pins.items()
            ),
            "basis_profile_id": "2904014_040",
            "basis_sha256": hashlib.sha256(profile_bytes).hexdigest(),
            "mutations": ["identity", "cycle", "observation time", "coordinates", "revision dates"],
            "run_id": str(run),
            "root_chunks": 270,
            "planned_incoming_occurrences": incoming,
            "planned_current_profiles_after_8_moves": expected,
            "levels_per_occurrence": 501,
            "planned_incoming_levels": incoming * 501,
            "weights_per_time_slice": [90, 40, 20],
            "occupied_month_tile_slots": 9,
            "month_slices": {"January": 1, "February": 1, "March": 1},
            "empty_roots": 261,
            "operations": rows,
            "progress": progress,
            "current_science": measurement,
            "measured_incoming_canonical_sizes": sizes,
            "per_publication_operations": per_publication,
            "state": state,
            "cap_bytes": 40 * 1024**3,
            "canonical_bytes": after_control["canonical_bytes"],
            "elapsed_seconds": time.monotonic() - started,
            "pipeline_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "cgroup_memory_peak_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text()),
            "cgroup_memory_limit_bytes": int(Path("/sys/fs/cgroup/memory.max").read_text()),
            "cgroup_memory_events": Path("/sys/fs/cgroup/memory.events").read_text(),
            "bounded_recovery": recoveries,
            "injected_publication_rebuild": rebuild,
            "complete_delivery_noops": noops,
            "deadlines_limits_unchanged": True,
            "budget_runs": 1,
            "upstream_calls": 0,
            "credential_reads": 0,
            "regional_population_observed": False,
            "report": report,
        }
        print(json.dumps(output, default=str))
        print("offline-regional-capacity-model-recorded")
    repository.close()
    admin.close()


if __name__ == "__main__":
    main()
