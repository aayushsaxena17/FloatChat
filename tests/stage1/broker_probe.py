"""Real PostgreSQL-queue acquire/process/supervise/schedule processes; no external route."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion.argovis import policy_versions, request_parameters
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.planning import (
    Interval,
    PlannedChunk,
    Tile,
    month_start,
    shift_months,
    timestamp,
)
from floatchat_core.ingestion.reporting import markdown_report, persisted_report
from floatchat_core.ingestion.repository import Repository
from psycopg.types.json import Jsonb

ENV = uuid.UUID("00000000-0000-4000-8000-000000000003")
INTERVAL = Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-01-07T00:00:00Z"))


# Barrier-patched production workers: `broker_fault_app.main` is the real CLI plus test barriers.
WORKER = "import sys, broker_fault_app; sys.exit(broker_fault_app.main(sys.argv[1:]))"


def wait(predicate, seconds=35):
    until = time.monotonic() + seconds
    while True:
        result = predicate()
        if result:
            return result
        assert time.monotonic() < until, "Offline broker proof timed out"
        time.sleep(0.1)


def main():
    admin = Repository(os.environ["INGESTION_DATABASE_URL"])
    admin.connection.execute("CREATE ROLE broker_ingestion LOGIN INHERIT")
    admin.connection.execute("GRANT floatchat_ingestor TO broker_ingestion")
    bucket = "floatchat-broker-proof"
    admin.connection.execute(
        "INSERT INTO app.ingestion_environment VALUES(%s,'broker','acceptance',true,"
        "%s,'broker','broker')",
        (ENV, bucket),
    )
    admin.connection.execute(
        "CREATE TABLE public.test_fault(chunk_id uuid PRIMARY KEY,phase text,"
        "lock_key bigint,armed boolean)"
    )
    admin.connection.execute(
        "CREATE TABLE public.test_signal(chunk_id uuid,phase text,worker_pid integer,"
        "backend_pid integer,at timestamptz)"
    )
    admin.connection.execute("GRANT SELECT ON public.test_fault TO floatchat_ingestor")
    admin.connection.execute("GRANT INSERT ON public.test_signal TO floatchat_ingestor")
    store = MinioStore(
        "http://127.0.0.1:9000",
        bucket,
        os.environ["MINIO_ROOT_USER"],
        os.environ["MINIO_ROOT_PASSWORD"],
    )
    wait(lambda: ready_store(store))
    store.client.create_bucket(Bucket=bucket)
    home = Path("/tmp/broker-home")
    home.mkdir()
    os.environ.update(
        HOME=str(home),
        INGESTION_DATABASE_URL="postgresql://broker_ingestion@127.0.0.1/broker_probe",
        INGESTION_ENVIRONMENT_ID=str(ENV),
        INGESTION_BUCKET=bucket,
        INGESTION_QUEUE_NAMESPACE="broker",
        COMPOSE_PROJECT_NAME="broker",
        OBJECT_STORAGE_ENDPOINT="http://127.0.0.1:9000",
        OBJECT_STORAGE_ACCESS_KEY=os.environ["MINIO_ROOT_USER"],
        OBJECT_STORAGE_SECRET_KEY=os.environ["MINIO_ROOT_PASSWORD"],
        INGESTION_APPLICATION_COMMIT="offline-broker-proof",
        FLOATCHAT_LIVE_INGESTION_ENABLED="false",
    )
    repository = Repository(os.environ["INGESTION_DATABASE_URL"])
    repository.connection.execute("SET ROLE floatchat_ingestor")
    processes = []
    logs = []
    evidence = []
    capture_root = Path("/test/tests/fixtures/argovis/recorded/6a8ffa52f6db4954b974c449e68c54bc")
    base = json.loads((capture_root / "02-profile.json").read_bytes())[0]
    metadata = json.loads((capture_root / "04-metadata.json").read_bytes())

    def start(arguments):
        log = tempfile.TemporaryFile()
        logs.append(log)
        child = subprocess.Popen([sys.executable, *arguments], stdout=log, stderr=log)
        processes.append(child)
        return child

    def supervise():
        return start(["-m", "floatchat_workers.cli", "supervise"])

    def worker(*command):
        # Production CLI with the fault barriers; pool children import them via run_ticket.
        return start(["-c", WORKER, *command])

    def cli(*arguments):
        return subprocess.run(
            [sys.executable, "-m", "floatchat_workers.cli", *arguments],
            capture_output=True,
            timeout=30,
        )

    def tickets(chunk, kind=None, started=None):
        rows = admin.connection.execute(
            "SELECT kind,started,claimed_by,fence FROM app.processing_ticket WHERE chunk_id=%s "
            "ORDER BY fence,kind",
            (chunk,),
        ).fetchall()
        return [
            row
            for row in rows
            if (kind is None or row["kind"] == kind)
            and (started is None or row["started"] == started)
        ]

    def create(root, count=1, seconds=600):
        root.mkdir()
        responses = []
        pieces = []
        for index in range(count):
            piece = PlannedChunk(INTERVAL, Tile(70 + 10 * index, 10))
            wire = dict(base)
            wire.update(
                _id="synthetic-broker-" + root.name + "-" + str(index),
                cycle_number=len(evidence) * 10 + index + 1000,
                timestamp="2025-01-02T00:00:00Z",
                geolocation={"type": "Point", "coordinates": [70 + 10 * index, 10]},
                data=[column[:3] for column in base["data"]],
            )
            pieces.append(piece)
            for role in ("inventory_before", "profile", "inventory_after"):
                doc = wire if role == "profile" else {k: v for k, v in wire.items() if k != "data"}
                data = json.dumps([doc]).encode()
                file = root / f"{index}-{role}.json"
                file.write_bytes(data)
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
        data = json.dumps(metadata).encode()
        (root / "metadata.json").write_bytes(data)
        responses.append(
            {
                "role": "metadata",
                "path": "/argo/meta",
                "parameters": {"id": metadata[0]["_id"]},
                "file": "metadata.json",
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
        admitted = repository.admit(
            ENV,
            uuid.uuid4(),
            "acceptance",
            INTERVAL,
            {"execution_seconds": seconds},
            input_kind="captured",
            descriptor={
                "fixture_index": str(index),
                "fixture_root": str(root),
                "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            },
        )
        run = uuid.UUID(admitted["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        assert epoch == 1
        with repository.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
        chunks = []
        for ordinal, piece in enumerate(pieces):
            chunk = uuid.uuid4()
            admin.connection.execute(
                "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
                "requested_end,tile,plan_version) VALUES(%s,%s,%s,%s,%s,%s,"
                "'explicit-component-not-regional')",
                (
                    chunk,
                    run,
                    str(ordinal),
                    INTERVAL.start,
                    INTERVAL.end,
                    Jsonb({"west": piece.tile.west, "south": 10, "width": 10, "height": 10}),
                ),
            )
            chunks.append(chunk)
        # Release the deliberately seeded controller to the real CLI supervisor.
        admin.connection.execute(
            "UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()"
            "-interval '1 second' WHERE id=%s",
            (run,),
        )
        return run, chunks

    def arm(chunk, phase):
        key = int(chunk.hex[:15], 16)
        admin.connection.execute("SELECT pg_advisory_lock(%s)", (key,))
        admin.connection.execute(
            "INSERT INTO public.test_fault VALUES(%s,%s,%s,true)", (chunk, phase, key)
        )
        return key

    def reached(chunk):
        return admin.connection.execute(
            "SELECT * FROM public.test_signal WHERE chunk_id=%s ORDER BY at DESC LIMIT 1", (chunk,)
        ).fetchone()

    def disarm(chunk, key):
        admin.connection.execute(
            "UPDATE public.test_fault SET armed=false WHERE chunk_id=%s", (chunk,)
        )
        admin.connection.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def closed(run):
        return repository.run(run)["closed"]

    def snapshot(run, case):
        report = persisted_report(repository, run)
        assert report["full_snapshot_balanced"] and report["run_eligible_balanced"]
        assert report["scientific_level_delta_balanced"]
        assert report["terminal_leaves"] == report["leaf_count"]
        assert not report["coverage"]["proved_complete"]
        evidence.append({"case": case, "report": report})
        return report

    try:
        acquire = worker("acquire", "--slots", "2")
        pool = worker("process", "--workers", "2")
        controller = supervise()
        # The workers exit at once on a configuration fault; a live pair is a ready queue.
        time.sleep(3)
        assert acquire.poll() is None and pool.poll() is None and controller.poll() is None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for phase in ("fetching", "landed", "validating", "publishing", "before_commit"):
                run, chunks = create(root / phase)
                chunk = chunks[0]
                key = arm(chunk, phase)
                found = wait(lambda chunk=chunk: reached(chunk))
                before = dict(repository.run(run))
                claimed = dict(repository.chunk(chunk))
                assert tickets(chunk, started=True)  # the worker we kill started its ticket
                os.kill(found["worker_pid"], signal.SIGKILL)
                disarm(chunk, key)
                if phase in ("fetching", "landed"):
                    # The acquire process hosts the killed thread; a service manager restarts it.
                    acquire.wait(timeout=10)
                    acquire = worker("acquire", "--slots", "2")
                assert repository.chunk(chunk)["state"] != "complete"
                admin.connection.execute(
                    "UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()"
                    "-interval '1 second' WHERE id=%s",
                    (chunk,),
                )
                wait(lambda run=run: closed(run))
                report = snapshot(run, "C05_worker_loss_" + phase)
                assert report["state"] == "complete"
                assert report["persisted_metrics"]["processing_recoveries"] == 1
                current = repository.chunk(chunk)
                # Recovery is one new claim; the acquire to process hand-over adds none.
                assert (
                    current["fence"] == claimed["fence"] + 1 and current["processing_claims"] == 2
                )
                assert (
                    repository.run(run)["run_reference_time_utc"]
                    == before["run_reference_time_utc"]
                )
                # The recovered claim is queued by phase: acquire work only before landing.
                recovered = tickets(chunk)
                assert {row["kind"] for row in recovered if row["fence"] == current["fence"]} == (
                    {"acquire", "process"} if phase == "fetching" else {"process"}
                )
                if phase != "fetching":
                    assert sum(item["attempts"] for item in report["payload_accounting"]) == 4
                else:
                    assert any(
                        item["disposition"] == "interrupted"
                        for item in report["payload_accounting"]
                    )
            run, chunks = create(root / "controller")
            chunk = chunks[0]
            key = arm(chunk, "fetching")
            wait(lambda: reached(chunk))
            epoch = repository.run(run)["control_epoch"]
            controller.kill()
            controller.wait(timeout=5)
            admin.connection.execute(
                "UPDATE public.test_fault SET armed=false WHERE chunk_id=%s", (chunk,)
            )
            admin.connection.execute(
                "UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()"
                "-interval '1 second' WHERE id=%s",
                (run,),
            )
            controller = supervise()
            wait(lambda: repository.run(run)["control_epoch"] == epoch + 1)
            admin.connection.execute("SELECT pg_advisory_unlock(%s)", (key,))
            wait(lambda: closed(run))
            report = snapshot(run, "C06_controller_process_loss")
            assert (
                report["state"] == "complete" and repository.run(run)["control_epoch"] == epoch + 1
            )
            run, chunks = create(root / "ack")
            chunk = chunks[0]
            key = arm(chunk, "after_commit")
            found = wait(lambda: reached(chunk))
            # The scientific transaction committed; the worker has not yet returned.
            assert repository.chunk(chunk)["state"] == "complete"
            (process_ticket,) = tickets(chunk, kind="process", started=True)
            ticket = admin.connection.execute(
                "SELECT id FROM app.processing_ticket WHERE chunk_id=%s AND kind='process'",
                (chunk,),
            ).fetchone()["id"]
            before_science = admin.connection.execute(
                "SELECT app.scientific_snapshot() AS value"
            ).fetchone()["value"]
            os.kill(found["worker_pid"], signal.SIGKILL)
            disarm(chunk, key)
            # A started ticket is never handed out again: the queue holds no work for it.
            assert not tickets(chunk, started=False)
            # A delivery of the same ticket (a lost acknowledgement) is recognized as complete.
            redelivery = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; from floatchat_workers.ingestion import process_ticket; "
                    "print(process_ticket(*sys.argv[1:4], 'process'))",
                    str(run),
                    str(chunk),
                    str(ticket),
                ],
                capture_output=True,
                timeout=60,
            )
            assert redelivery.stdout.decode().strip() == "complete", redelivery.stderr[-2000:]
            wait(lambda: closed(run))
            report = snapshot(run, "P07_C11_commit_before_lost_ack_redelivery")
            after_science = admin.connection.execute(
                "SELECT app.scientific_snapshot() AS value"
            ).fetchone()["value"]
            for field in (
                "profiles",
                "measurement_levels",
                "profile_manifest_sha256",
                "active_generation_sha256",
                "attempts",
            ):
                assert before_science[field] == after_science[field]
            assert repository.chunk(chunk)["processing_claims"] == 1
            assert process_ticket["claimed_by"] is not None
            for operation in ("cancel", "deadline"):
                run, chunks = create(
                    root / operation, count=2, seconds=90 if operation == "deadline" else 600
                )
                key = arm(chunks[1], "before_commit")
                wait(lambda chunks=chunks: reached(chunks[1]))
                wait(lambda chunks=chunks: repository.chunk(chunks[0])["state"] == "complete")
                if operation == "cancel":
                    cancellation = subprocess.run(
                        [sys.executable, "-m", "floatchat_workers.cli", "cancel", str(run)],
                        capture_output=True,
                        timeout=10,
                    )
                    assert cancellation.returncode == 130
                wait(lambda run=run: closed(run), 45)
                disarm(chunks[1], key)
                report = snapshot(
                    run,
                    "C07_operator_cancelled"
                    if operation == "cancel"
                    else "C08_real_deadline_expiry",
                )
                assert (
                    report["state"] == "partial"
                    and repository.chunk(chunks[0])["state"] == "complete"
                )
                assert repository.chunk(chunks[1])["state"] == "failed"
                assert report["termination_reason"] == (
                    "operator_cancelled" if operation == "cancel" else "deadline_expired"
                )
                assert (
                    report["persisted_metrics"]["replacement_levels"]["inserted_replacement_levels"]
                    == 3
                )
            # The active-chunk bound is the environment's, not a constant: 2 here (default 8).
            admin.connection.execute("UPDATE app.ingestion_environment SET max_active_chunks=2")
            run, chunks = create(root / "two_chunks", count=3)
            keys = [arm(chunk, "fetching") for chunk in chunks[:2]]
            signals = [wait(lambda chunk=chunk: reached(chunk)) for chunk in chunks[:2]]
            # Two acquire threads of the one acquire process, each with its own connection.
            assert len({row["worker_pid"] for row in signals}) == 1
            assert len({row["backend_pid"] for row in signals}) == 2
            assert repository.chunk(chunks[2])["processing_claims"] == 0
            for chunk, key in zip(chunks[:2], keys, strict=True):
                disarm(chunk, key)
            wait(lambda: closed(run))
            snapshot(run, "B02_two_active_chunks_third_chunk_waits")
            # `schedule` is one admission under the environment advisory lock (164993423,2).
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "true"
            refused = cli("schedule")
            assert refused.returncode == 2
            assert refused.stdout.decode().strip() == "acceptance_schedule_disabled"
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "false"
            disabled = cli("schedule")
            assert disabled.returncode == 0
            assert disabled.stdout.decode().strip() == "live_ingestion_disabled"
            evidence.append({"case": "D01_acceptance_schedule_refused", "refused": True})
            # A separate physical database represents normal scheduling. Never mix
            # historical science into a normal environment.
            normal_admin = Repository("postgresql://postgres@127.0.0.1/schedule_probe")
            normal_env = uuid.uuid4()
            normal_admin.connection.execute(
                "INSERT INTO app.ingestion_environment VALUES(%s,'schedule-proof','normal',true,"
                "'schedule-proof','schedule-proof','schedule-proof')",
                (normal_env,),
            )
            os.environ.update(
                INGESTION_DATABASE_URL="postgresql://broker_ingestion@127.0.0.1/schedule_probe",
                INGESTION_ENVIRONMENT_ID=str(normal_env),
                INGESTION_BUCKET="schedule-proof",
                INGESTION_QUEUE_NAMESPACE="schedule-proof",
                COMPOSE_PROJECT_NAME="schedule-proof",
            )
            normal_repository = Repository(os.environ["INGESTION_DATABASE_URL"])
            normal_repository.connection.execute("SET ROLE floatchat_ingestor")
            last = month_start(datetime.now(UTC))
            first = shift_months(last, -1)
            incumbent = normal_repository.admit(
                normal_env,
                uuid.uuid4(),
                "normal",
                Interval(first, last),
                {"execution_seconds": 600},
                input_kind="captured",
                descriptor={"never_executed": True},
            )
            before_watermark = normal_admin.connection.execute(
                "SELECT watermark FROM app.ingestion_scope"
            ).fetchone()["watermark"]
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "true"
            overlap = cli(
                "ingest",
                "--mode",
                "normal",
                "--from",
                first.strftime("%Y-%m"),
                "--to",
                first.strftime("%Y-%m"),
                "--live-opt-in",
            )
            assert overlap.returncode == 6 and json.loads(overlap.stdout)["kind"] == "overlap_skip"

            def attempts():
                return normal_admin.connection.execute(
                    "SELECT count(*) AS n FROM app.scheduling_attempt"
                ).fetchone()["n"]

            def schedule_lock():
                return normal_admin.connection.execute(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' "
                    "AND classid=164993423 AND objid=2 AND granted"
                ).fetchone()

            scheduled = cli("schedule")
            assert scheduled.returncode == 0
            assert scheduled.stdout.decode().strip() == "overlap_skip"
            assert attempts() == 2
            assert (
                normal_admin.connection.execute(
                    "SELECT count(*) AS n FROM app.ingestion_run"
                ).fetchone()["n"]
                == 1
            )
            assert (
                normal_admin.connection.execute(
                    "SELECT watermark FROM app.ingestion_scope"
                ).fetchone()["watermark"]
                == before_watermark
            )
            assert (
                normal_admin.connection.execute(
                    "SELECT count(*) AS n FROM app.ingestion_attempt"
                ).fetchone()["n"]
                == 0
            )
            assert schedule_lock() is None  # released when the one-shot command ended
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "false"
            normal_repository.finalize(uuid.UUID(incumbent["run_id"]), "operator_cancelled")
            evidence.append(
                {
                    "case": "D05_D06_real_manual_and_scheduled_overlap",
                    "manual_exit": 6,
                    "admission_events": 2,
                    "runs": 1,
                    "watermark_unchanged": True,
                    "upstream_attempts": 0,
                }
            )
            # A peer already holding the advisory lock makes the timer unit skip, not admit.
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "true"
            normal_admin.connection.execute("SELECT pg_advisory_lock(164993423,2)")
            held = cli("schedule")
            assert held.returncode == 0
            assert held.stdout.decode().strip() == "schedule_already_running"
            assert attempts() == 2 and schedule_lock() is not None
            normal_admin.connection.execute("SELECT pg_advisory_unlock(164993423,2)")
            os.environ["FLOATCHAT_LIVE_INGESTION_ENABLED"] = "false"
            evidence.append(
                {
                    "case": "D01_schedule_singleton_lock",
                    "one_lock": True,
                    "peer_skipped": True,
                    "lock_released_after_run": True,
                    "disabled_no_scheduled_ingestion": True,
                }
            )
            assert acquire.poll() is None and pool.poll() is None and controller.poll() is None
            # Persist a machine-readable/Markdown representative run report too.
            final_report = next(
                item["report"] for item in evidence if item["case"] == "C08_real_deadline_expiry"
            )
            output = {
                "kind": "offline_real_queue_multiprocess_evidence",
                "contract": "stage1-v4",
                "cases": evidence,
                "queue": "postgresql_skip_locked",
                "acquire": "one process, two threads",
                "worker_pool": "spawn_single_use_children",
                "concurrency": 2,
                "task_retry_owner": "durable_controller_only",
                "acknowledgement": "started ticket never re-claimed; committed redelivery "
                "recognized as terminal",
                "lease_expiry": "Accelerated only by privileged disposable test fixture; "
                "run reference/deadline/limits remain immutable",
                "external_network": "none",
                "input": "Labelled synthetic derivatives of authentic sanitized capture; "
                "explicit component chunks, not regional coverage",
            }
            print(json.dumps(output, default=str, sort_keys=True))
            Path("/tmp/broker-report.md").write_text(markdown_report(final_report))
            normal_repository.close()
            normal_admin.close()
    finally:
        for child in reversed(processes):
            if child.poll() is None:
                child.terminate()
        for child in processes:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for log in logs:
            log.close()
        repository.close()
        admin.close()


def ready_store(store):
    try:
        store.client.list_buckets()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
