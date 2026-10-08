"""Real publication path on labelled authentic derivatives, not regional acceptance."""

import copy
import hashlib
import json
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from floatchat_core.ingestion.argovis import policy_versions, request_parameters
from floatchat_core.ingestion.planning import Interval, PlannedChunk, Tile, timestamp
from floatchat_core.ingestion.reporting import persisted_report
from floatchat_workers.ingestion import process_ticket
from psycopg.types.json import Jsonb


def verify_capacity(repository, environment, store=None):
    basis = Path("/test/tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45")
    profile_bytes = (basis / "02-profile.json").read_bytes()
    metadata_bytes = (basis / "04-metadata.json").read_bytes()
    authentic = json.loads(profile_bytes)[0]
    assert authentic["_id"] == "2904014_040"
    start, end = timestamp("2025-01-01T00:00:00Z"), timestamp("2025-02-01T00:00:00Z")
    pieces = [
        PlannedChunk(
            Interval(start + timedelta(days=7 * i), min(start + timedelta(days=7 * (i + 1)), end)),
            Tile(80, -30),
        )
        for i in range(5)
    ]
    # Five month-bounded slices fill one slot with five parts of 8 profiles each (stage1-v4:
    # a chunk publishes only its own profiles); the active objects hold 8 -> 16 -> ... -> 40
    # profiles in total, each with the source's complete 501-level A-mode column set.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        responses = []
        for index, piece in enumerate(pieces):
            documents = []
            for ordinal in range(8):
                value = copy.deepcopy(authentic)
                value["_id"] = f"synthetic-capacity-{index * 8 + ordinal:04d}"
                value["cycle_number"] = 9000 + index * 8 + ordinal
                value["timestamp"] = (piece.interval.start + timedelta(hours=12)).isoformat()
                value["geolocation"]["coordinates"] = [85, -25]
                documents.append(value)
            for role in ("inventory_before", "profile", "inventory_after"):
                raw = json.dumps(documents, separators=(",", ":")).encode()
                file = root / f"{index}-{role}.json"
                file.write_bytes(raw)
                responses.append(
                    {
                        "role": role,
                        "path": "/argo",
                        "parameters": request_parameters(piece, inventory=role != "profile"),
                        "file": file.name,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    }
                )
        for metadata in json.loads(metadata_bytes):
            raw = json.dumps([metadata]).encode()
            file = root / ("meta-" + uuid.uuid4().hex + ".json")
            file.write_bytes(raw)
            responses.append(
                {
                    "role": "metadata",
                    "path": "/argo/meta",
                    "parameters": {"id": metadata["_id"]},
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
            Interval(start, end),
            {"execution_seconds": 600},
            input_kind="captured",
            descriptor={
                "fixture_index": str(index),
                "fixture_root": str(root),
                "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            },
        )
        run = uuid.UUID(admitted["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        with repository.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
        chunks = []
        repository.connection.execute("RESET ROLE")
        for piece in pieces:
            chunk = uuid.uuid4()
            repository.connection.execute(
                "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
                "requested_end,tile,plan_version) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    chunk,
                    run,
                    piece.interval.start.isoformat(),
                    piece.interval.start,
                    piece.interval.end,
                    Jsonb({"west": 80, "south": -30, "width": 10, "height": 10}),
                    "synthetic-capacity-component",
                ),
            )
            chunks.append(chunk)
        repository.connection.execute("SET ROLE floatchat_ingestor")
        progress = []
        for ordinal, chunk in enumerate(chunks):
            authority = repository.claim(run, chunk, epoch)
            assert authority is not None
            ticket = repository.ticket(authority)
            assert process_ticket(str(run), str(chunk), str(ticket), "execute") == "complete"
            with repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute(
                    "SELECT sum(profile_count) AS profiles,sum(row_count) AS levels "
                    "FROM app.committed_active_partitions WHERE logical_key LIKE %s",
                    ("%/2025-01/80:-30%",),
                )
                membership = dict(cursor.fetchone())
            assert membership["profiles"] == (ordinal + 1) * 8, membership
            assert membership["levels"] == (ordinal + 1) * 8 * 501, membership
            progress.append(
                {
                    "chunk": str(chunk),
                    "canonical_bytes": repository.run(run)["canonical_bytes"],
                    "retained_profiles": int(membership["profiles"]),
                    "retained_levels": int(membership["levels"]),
                }
            )
        assert repository.finalize(run) == "complete"
        report = persisted_report(repository, run)
        assert report["final_evidence_frozen"] and not report["coverage"]["proved_complete"]
        assert report["full_snapshot_balanced"] and report["run_eligible_balanced"]
        assert report["active_part_count"] == 5 and report["active_snapshot_count"] == 0, (
            report["active_part_count"],
            report["active_snapshot_count"],
            report["active_partitions"],
        )
        assert (
            report["persisted_metrics"]["resource_counters"]["canonical_bytes"]
            < 10 * 1024**3 - 16 * 1024**2
        )
        compaction = None
        if store is not None:
            # The compact job merges the five parts into one snapshot of the whole slot.
            with repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute("SELECT DISTINCT logical_key FROM app.committed_active_partitions")
                (slot,) = [row["logical_key"] for row in cursor.fetchall()]
            started = time.monotonic()
            assert repository.compact(environment, slot, store, time.monotonic() + 300) == (
                "compacted"
            )
            with repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute(
                    "SELECT kind,profile_count,row_count FROM app.committed_active_partitions"
                )
                (merged,) = [dict(row) for row in cursor.fetchall()]
            assert merged == {"kind": "snapshot", "profile_count": 40, "row_count": 40 * 501}
            assert repository.compact(environment, slot, store, time.monotonic() + 30) == (
                "unchanged"
            )
            compaction = {**merged, "seconds": round(time.monotonic() - started, 3)}
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT sum(w.actual_bytes) AS bytes,count(*) AS operations "
                "FROM app.canonical_work w JOIN app.ingestion_chunk c ON c.id=w.chunk_id "
                "WHERE c.run_id=%s",
                (run,),
            )
            work = dict(cursor.fetchone())
        assert (
            int(work["bytes"])
            == report["persisted_metrics"]["resource_counters"]["canonical_bytes"]
        )
        # Explicit model of aggregate exhaustion, not a measured workload. The
        # successful run above supplies the independently measured capacity.
        exhausted = repository.admit(
            environment,
            uuid.uuid4(),
            "acceptance",
            Interval(start, end),
            {"execution_seconds": 600},
            input_kind="captured",
            descriptor={
                "fixture_index": str(index),
                "fixture_root": str(root),
                "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            },
        )
        exhausted_run = uuid.UUID(exhausted["run_id"])
        exhausted_epoch = repository.start_controller(exhausted_run, uuid.uuid4())
        with repository.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (exhausted_run, exhausted_epoch))
        exhausted_chunk = uuid.uuid4()
        repository.connection.execute("RESET ROLE")
        repository.connection.execute(
            "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
            "requested_end,tile,plan_version) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                exhausted_chunk,
                exhausted_run,
                "synthetic-exhaustion-model",
                pieces[0].interval.start,
                pieces[0].interval.end,
                Jsonb({"west": 80, "south": -30, "width": 10, "height": 10}),
                "synthetic-exhaustion-model",
            ),
        )
        repository.connection.execute(
            "INSERT INTO app.canonical_work(id,chunk_id,fence,status,reserved_bytes,actual_bytes) "
            "SELECT gen_random_uuid(),%s,1,'complete',16777216,"
            "CASE WHEN n=640 THEN 1016688 ELSE 16777216 END FROM generate_series(1,640) n",
            (exhausted_chunk,),
        )
        repository.connection.execute(
            "UPDATE app.ingestion_run SET canonical_bytes=42933912432 WHERE id=%s",
            (exhausted_run,),
        )
        repository.connection.execute("SET ROLE floatchat_ingestor")
        exhausted_authority = repository.claim(exhausted_run, exhausted_chunk, exhausted_epoch)
        assert exhausted_authority is not None
        exhausted_ticket = repository.ticket(exhausted_authority)
        assert (
            process_ticket(
                str(exhausted_run), str(exhausted_chunk), str(exhausted_ticket), "execute"
            )
            == "quarantined"
        )
        assert repository.finalize(exhausted_run) == "quarantined"
        exhausted_report = persisted_report(repository, exhausted_run)
        expected_limit = {
            "scope": "run",
            "operation": "reservation",
            "limit_bytes": 42949672960,
            "used_bytes": 42933912432,
            "requested_bytes": 16777216,
        }
        assert exhausted_report["final_evidence_frozen"]
        assert exhausted_report["scientific_no_change"]
        assert exhausted_report["active_partition_no_change"]
        assert exhausted_report["persisted_metrics"]["resource_limits"][0]["resource_limit"] == (
            expected_limit
        )
        assert exhausted_report["persisted_metrics"]["resource_counters"]["canonical_bytes"] == (
            42933912432
        )
        return {
            "kind": "synthetic_authentic_derivative_real_publication_capacity",
            "basis_profile_id": "2904014_040",
            "basis_profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
            "basis_metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "source_levels": 501,
            "mutations": ["profile ID", "cycle", "observation time", "position"],
            "run_id": str(run),
            "chunks": progress,
            "canonical_bytes": int(work["bytes"]),
            "canonical_operations": work["operations"],
            "approved_cap_bytes": 10 * 1024**3,
            "publication_complete": True,
            "final_evidence_frozen": True,
            "regional_coverage_proved": False,
            "live_calls": 0,
            "parts_before_compaction": report["active_part_count"],
            "compaction": compaction,
            # Match the CLI's persisted-report export for UUIDs, datetimes and
            # PostgreSQL numeric aggregates; scientific counters stay numeric.
            "report": json.loads(json.dumps(report, default=str)),
            "exhaustion_model": {
                "input": "Explicit synthetic administrative counter/ledger seeding",
                "run_id": str(exhausted_run),
                "state": exhausted_report["state"],
                "resource_limit": expected_limit,
                "scientific_no_change": exhausted_report["scientific_no_change"],
                "active_partition_no_change": exhausted_report["active_partition_no_change"],
                "final_evidence_frozen": exhausted_report["final_evidence_frozen"],
                "unchanged_bytes": 42933912432,
            },
            "scope": "Five parts of one month/tile slot compacted into one snapshot, real "
            "restricted PostgreSQL and MinIO verification and commits; not Jan–Mar regional "
            "capacity or whole-pipeline memory proof.",
        }
