"""Real restricted repository + MinIO; only HTTP transport is synthetic."""

import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion import transport as transport_module
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.reporting import markdown_report, persisted_report
from floatchat_core.ingestion.transport import HTTPFailure, Response
from psycopg.types.json import Jsonb

# Retry ownership/persistence proof; the backoff policy is pinned in test_wire.
transport_module.RETRY_MAXIMA = {1: 0.0, 2: 0.0, 3: 0.0}


def verify_http_path(repository, store, environment, piece):
    evidence = []
    frozen = []
    scenarios = ((429, 503, 200), (401,), (403,), (503, 503, 503, 503))
    for statuses in scenarios:
        result = repository.admit(
            environment,
            uuid.uuid4(),
            "acceptance",
            piece.interval,
            {"execution_seconds": 600},
            input_kind="live",
            descriptor={"live_opt_in": True},
        )
        run = uuid.UUID(result["run_id"])
        epoch = repository.start_controller(run, uuid.uuid4())
        chunk = uuid.uuid4()
        with repository.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
        repository.connection.execute("RESET ROLE")
        repository.connection.execute(
            "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
            "requested_end,tile,plan_version) VALUES(%s,%s,'http-component',%s,%s,%s,'component')",
            (
                chunk,
                run,
                piece.interval.start,
                piece.interval.end,
                Jsonb({"west": 70, "south": 10, "width": 10, "height": 10}),
            ),
        )
        repository.connection.execute("SET ROLE floatchat_ingestor")
        authority = repository.claim(run, chunk, epoch)
        repository.transition(authority, "fetching", "offline_http_probe")
        calls = []

        def transport(
            path, parameters, credential, account, *, statuses=statuses, calls=calls, **kwargs
        ):
            assert path == "/argo" and parameters == {"id": "synthetic-http-probe"}
            assert credential == "offline-transport-sentinel"
            status = statuses[len(calls)]
            calls.append(status)
            if status != 200:
                raise HTTPFailure(status, "0" if status == 429 else None)
            account(2)
            return Response(b"[]", 2, datetime.now(UTC), {})

        with tempfile.TemporaryDirectory() as directory:
            owner = RequestOwner(
                repository,
                store,
                authority,
                deadline=time.monotonic() + 60,
                application_commit="offline-http-component",
                enabled=lambda: True,
                credential=lambda: "offline-transport-sentinel",
                transport=transport,
                originals=Path(directory) / "originals",
                jitter=lambda: 0,
            )
            if statuses[-1] == 200:
                assert (
                    owner.obtain("/argo", {"id": "synthetic-http-probe"}, "profile").payload
                    == b"[]"
                )
                # Verified landing reuse must not make a fifth/new HTTP call.
                assert (
                    owner.obtain("/argo", {"id": "synthetic-http-probe"}, "profile").payload
                    == b"[]"
                )
            else:
                try:
                    owner.obtain("/argo", {"id": "synthetic-http-probe"}, "profile")
                except Rejection as error:
                    assert error.category == "http_retry_exhausted"
                else:
                    raise AssertionError("Expected terminal HTTP failure")
        assert calls == list(statuses)
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT disposition,http_status,error_category,finished_at,request_attempt "
                "FROM app.ingestion_attempt WHERE chunk_id=%s ORDER BY attempt_number",
                (chunk,),
            )
            attempts = cursor.fetchall()
        assert [row["http_status"] for row in attempts] == list(statuses)
        assert [row["request_attempt"] for row in attempts] == list(range(1, len(statuses) + 1))
        assert all(row["finished_at"] is not None for row in attempts)
        assert [row["disposition"] for row in attempts] == [
            "verified_raw" if status == 200 else "http_failure" for status in statuses
        ]
        assert [row["error_category"] for row in attempts] == [
            None if status == 200 else "upstream_http_failure" for status in statuses
        ]
        repository.transition(
            authority,
            "failed",
            "http_retry_exhausted" if statuses[-1] != 200 else "component_request_probe_complete",
        )
        assert repository.finalize(run) == "failed"
        report = persisted_report(repository, run)
        metrics = report["persisted_metrics"]
        assert metrics["resource_counters"]["http_attempts"] == len(statuses)
        assert metrics["http_retries"] == len(statuses) - 1
        assert all(row["unfinished_attempts"] == 0 for row in metrics["attempt_timing"])
        assert all(row["elapsed_seconds_sum"] > 0 for row in metrics["attempt_timing"])
        assert report["final_evidence_frozen"]
        frozen.append((run, report, markdown_report(report)))
        assert report["scientific_no_change"] and report["active_partition_no_change"]
        evidence.append(
            {
                "run_id": str(run),
                "chunk_id": str(chunk),
                "statuses": list(statuses),
                "dispositions": [row["disposition"] for row in attempts],
                "http_retries": metrics["http_retries"],
                "attempts": len(attempts),
                "timings_finished": True,
                "positive_elapsed_timings": True,
                "safe_error_categories": True,
                "frozen_resource_counters": metrics["resource_counters"],
                "state_reasons": metrics["state_reasons"],
                "scientific_no_change": True,
                "scope": "Real repository/MinIO, mocked HTTP; request-only component",
            }
        )
    for run, report, rendered in frozen:
        assert persisted_report(repository, run) == report
        assert markdown_report(persisted_report(repository, run)) == rendered
    for item in evidence:
        item["frozen_reporting_identical_after_later_runs"] = True
    evidence.append(verify_metadata_cache(repository, store, environment, piece))
    return evidence


def verify_metadata_cache(repository, store, environment, piece):
    """stage1-v4 float metadata cache against the real tables (requires migration 0012).

    Chunk 1 fetches and upserts; chunk 2 of the same run is served by a per-chunk
    `cache` attempt and manifest with no request (fresh: retrieved after the run was
    created, whatever its reference time); chunk 2 reloads it by verified_landing.
    """
    result = repository.admit(
        environment,
        uuid.uuid4(),
        "acceptance",
        piece.interval,
        {"execution_seconds": 600},
        input_kind="live",
        descriptor={"live_opt_in": True},
    )
    run = uuid.UUID(result["run_id"])
    epoch = repository.start_controller(run, uuid.uuid4())
    with repository.transaction() as cursor:
        cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
    chunks = [uuid.uuid4(), uuid.uuid4()]
    repository.connection.execute("RESET ROLE")
    for number, chunk in enumerate(chunks):
        repository.connection.execute(
            "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
            "requested_end,tile,plan_version) VALUES(%s,%s,%s,%s,%s,%s,'component')",
            (
                chunk,
                run,
                f"cache-component-{number}",
                piece.interval.start,
                piece.interval.end,
                Jsonb({"west": 70, "south": 10, "width": 10, "height": 10}),
            ),
        )
    repository.connection.execute("SET ROLE floatchat_ingestor")
    authorities = [repository.claim(run, chunk, epoch) for chunk in chunks]
    for authority in authorities:
        repository.transition(authority, "fetching", "offline_cache_probe")
    parameters = {"id": "synthetic-cache-probe"}
    payload = b'[{"_id":"synthetic-cache-probe","n":1.00}]'
    calls = []

    def transport(path, parameters, credential, account, **kwargs):
        calls.append(parameters["id"])
        account(len(payload))
        return Response(payload, len(payload), datetime.now(UTC), {})

    def refuse(*args, **kwargs):
        raise AssertionError("Cache hit and reload must not request")

    with tempfile.TemporaryDirectory() as directory:

        def owner(authority, transport, require_existing=False):
            return RequestOwner(
                repository,
                store,
                authority,
                deadline=time.monotonic() + 60,
                application_commit="offline-cache-component",
                enabled=lambda: True,
                credential=lambda: "offline-transport-sentinel",
                transport=transport,
                originals=Path(directory) / "originals",
                jitter=lambda: 0,
                require_existing=require_existing,
            )

        first = owner(authorities[0], transport).obtain("/argo/meta", parameters, "metadata")
        second = owner(authorities[1], refuse).obtain("/argo/meta", parameters, "metadata")
        reloaded = owner(authorities[1], refuse, True).obtain("/argo/meta", parameters, "metadata")
    assert calls == ["synthetic-cache-probe"] and first.payload == second.payload
    assert str(reloaded.manifest["id"]) == str(second.manifest["id"])
    with repository.transaction(readonly_snapshot=True) as cursor:
        cursor.execute(
            "SELECT a.chunk_id,a.origin,a.disposition,a.http_status,m.object_key,m.id AS manifest "
            "FROM app.ingestion_attempt a JOIN app.raw_manifest m ON m.attempt_id=a.id "
            "WHERE a.chunk_id=ANY(%s) ORDER BY a.attempt_number",
            (chunks,),
        )
        rows = {row["chunk_id"]: row for row in cursor.fetchall()}
        cursor.execute(
            "SELECT raw_manifest_id FROM app.float_metadata_cache WHERE pointer=%s",
            (parameters["id"],),
        )
        cached = cursor.fetchone()
    assert [rows[chunk]["origin"] for chunk in chunks] == ["http", "cache"]
    assert {row["disposition"] for row in rows.values()} == {"verified_raw"}
    assert rows[chunks[0]]["object_key"] == rows[chunks[1]]["object_key"]
    assert rows[chunks[0]]["manifest"] != rows[chunks[1]]["manifest"]
    assert cached["raw_manifest_id"] == rows[chunks[0]]["manifest"]
    for authority in authorities:
        repository.transition(authority, "failed", "component_cache_probe_complete")
    assert repository.finalize(run) == "failed"
    return {
        "run_id": str(run),
        "chunks": [str(chunk) for chunk in chunks],
        "origins": ["http", "cache"],
        "requests": len(calls),
        "same_object_distinct_manifests": True,
        "reload_by_verified_landing": True,
        "scope": "Real repository/MinIO, mocked HTTP; metadata cache component",
    }
