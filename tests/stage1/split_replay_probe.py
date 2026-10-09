"""Actual --replay-run on a validated, temporally/spatially split synthetic plan.

All source responses are labelled synthetic. The disposable network namespace has
no external egress; upstream transport and credential access are additionally denied.
"""

import copy
import hashlib
import json
import threading
import time
import uuid
from datetime import timedelta

from floatchat_core.ingestion.argovis import policy_versions, request_parameters
from floatchat_core.ingestion.controller import Controller
from floatchat_core.ingestion.planning import month_interval, plan, split, timestamp
from floatchat_core.ingestion.reporting import persisted_report
from floatchat_workers import cli, ingestion


def verify_split_replay(repository, environment, wire, metadata, root):
    interval = month_interval("2025-01", "2025-01")
    roots = list(plan(interval))
    temporal = next(
        p for p in roots if p.tile.west == 70 and p.tile.south == 10 and p.interval.start.day == 1
    )
    # Plan v2: one 31-day January root per tile; halving reaches 2,678,400 s / 2**9.
    spatial = next(p for p in roots if p.tile.west == 80 and p.tile.south == 10)
    leaves = [p for p in roots if p not in (temporal, spatial)]
    leaves.extend(split(temporal))
    current = spatial
    while current.interval.end - current.interval.start >= timedelta(hours=2):
        first, second = split(current)
        leaves.append(second)
        current = first
    assert current.interval.end - current.interval.start == timedelta(seconds=5231.25)
    leaves.extend(split(current))
    raw = copy.deepcopy(wire)
    raw["_id"] = "synthetic-split-replay"
    raw["cycle_number"] += 10000
    raw["timestamp"] = "2025-01-03T00:00:00Z"
    raw["geolocation"]["coordinates"] = [70.001, 10.001]
    root.mkdir()
    empty = root / "empty.json"
    full = root / "profile.json"
    empty.write_bytes(b"[]")
    full.write_bytes(json.dumps([raw]).encode())
    responses = []
    for piece in leaves:
        selected = (
            piece.interval.contains(timestamp(raw["timestamp"]))
            and piece.tile.west == 70
            and piece.tile.south == 10
        )
        payload = full if selected else empty
        for role in ("inventory_before", "profile", "inventory_after"):
            responses.append(
                {
                    "role": role,
                    "path": "/argo",
                    "parameters": request_parameters(piece, inventory=role != "profile"),
                    "file": payload.name,
                    "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                    "retrieved_at_utc": "2026-10-06T00:00:00+00:00",
                }
            )
    for index, document in enumerate(metadata):
        payload = root / f"metadata-{index}.json"
        payload.write_bytes(json.dumps([document]).encode())
        responses.append(
            {
                "role": "metadata",
                "path": "/argo/meta",
                "parameters": {"id": document["_id"]},
                "file": payload.name,
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "retrieved_at_utc": "2026-10-06T00:00:00+00:00",
            }
        )
    index_path = root / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "kind": "synthetic_offline_chunk_fixture",
                "versions": policy_versions(),
                "responses": responses,
            }
        )
    )
    descriptor = {
        "fixture_index": str(index_path),
        "fixture_root": str(root),
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    }
    predecessor = uuid.UUID(
        repository.admit(
            environment,
            uuid.uuid4(),
            "acceptance",
            interval,
            {"execution_seconds": 1200},
            input_kind="captured",
            descriptor=descriptor,
        )["run_id"]
    )
    epoch = repository.start_controller(predecessor, uuid.uuid4())
    repository.persist_plan(predecessor, epoch)

    def find_piece(piece):
        return next(
            c
            for c in repository.chunks(predecessor)
            if c["leaf"]
            and c["requested_start"] == piece.interval.start
            and c["requested_end"] == piece.interval.end
            and c["tile"]
            == {
                "west": piece.tile.west,
                "south": piece.tile.south,
                "width": piece.tile.width,
                "height": piece.tile.height,
            }
        )

    authority = repository.claim(predecessor, find_piece(temporal)["id"], epoch)
    repository.split(authority)
    current = spatial
    while current.interval.end - current.interval.start >= timedelta(hours=2):
        repository.split(repository.claim(predecessor, find_piece(current)["id"], epoch))
        current = split(current)[0]
    repository.split(repository.claim(predecessor, find_piece(current)["id"], epoch))
    predecessor_chunks = repository.chunks(predecessor)
    assert sum(c["leaf"] for c in predecessor_chunks) == len(leaves)
    assert any(c["tile"]["width"] == 5 for c in predecessor_chunks)
    for chunk in predecessor_chunks:
        if not chunk["leaf"]:
            continue
        authority = repository.claim(predecessor, chunk["id"], epoch)
        ticket = repository.ticket(authority)
        assert (
            ingestion.process_ticket(str(predecessor), str(chunk["id"]), str(ticket), "execute")
            == "complete"
        )
        repository.controller_heartbeat(predecessor, epoch)
    assert repository.finalize(predecessor) == "complete"
    predecessor_chunks = repository.chunks(predecessor)
    baseline = persisted_report(repository, predecessor)
    assert baseline["state"] == "complete"

    def denied(*args, **kwargs):
        raise AssertionError("Replay must not access upstream or credentials")

    original_request_owner = ingestion.RequestOwner
    original_credential = ingestion.upstream_credential
    original_sleep_module = cli.time
    ingestion.RequestOwner = denied
    ingestion.upstream_credential = denied
    # The production CLI is invoked with its real parser/month validation. Only
    # polling cadence is shortened; all plan, repository and worker paths are real.
    from types import SimpleNamespace

    cli.time = SimpleNamespace(sleep=lambda _: time.sleep(0.01))
    result = []
    request = uuid.uuid4()
    thread = threading.Thread(
        target=lambda: result.append(
            cli.main(
                [
                    "ingest",
                    "--mode",
                    "acceptance",
                    "--from",
                    "2025-01",
                    "--to",
                    "2025-01",
                    "--replay-run",
                    str(predecessor),
                    "--request-id",
                    str(request),
                    "--execution-seconds",
                    "1200",
                ]
            )
        )
    )
    try:
        thread.start()
        limit = time.monotonic() + 600
        target = None
        while target is None:
            with repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute(
                    "SELECT id AS run_id FROM app.ingestion_run WHERE request_id=%s", (request,)
                )
                row = cursor.fetchone()
            if row:
                target = row["run_id"]
            else:
                assert thread.is_alive() and time.monotonic() < limit, result
                time.sleep(0.01)

        def dispatch(authority, kind):
            # Serial execute path: the default process ticket is enough whatever the phase kind.
            ticket = repository.ticket(authority)
            state = ingestion.process_ticket(
                str(authority.run), str(authority.chunk), str(ticket), "execute"
            )
            assert state == "complete", state

        controller = Controller(repository, target, dispatch)
        while not repository.run(target)["closed"]:
            assert time.monotonic() < limit, "Replay deadline exceeded"
            controller.tick()
        thread.join(timeout=10)
        assert result == [0] and not thread.is_alive(), result
        replay = persisted_report(repository, target)
        assert replay["state"] == "complete"
        assert replay["scientific_no_change"] and replay["active_partition_no_change"]
        assert replay["active_generation_ids"] == baseline["active_generation_ids"]
        assert replay["full_snapshot_balanced"] and replay["run_eligible_balanced"]
        assert replay["after_at_report_snapshot"]["attempts"] > replay["before"]["attempts"]
        assert replay["after_at_report_snapshot"]["audit_rows"] > replay["before"]["audit_rows"]
        assert replay["full_snapshot_balanced"] and replay["run_eligible_balanced"]
        assert replay["persisted_metrics"]["source_attribution"]["input_kind"] == "replay"
        chunks = repository.chunks(target)

        def topology(rows):
            return sorted(
                (
                    c["requested_start"].isoformat(),
                    c["requested_end"].isoformat(),
                    json.dumps(c["tile"], sort_keys=True),
                    c["leaf"],
                )
                for c in rows
            )

        assert topology(chunks) == topology(predecessor_chunks)
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM app.replay_chunk_source WHERE run_id=%s", (target,)
            )
            assert cursor.fetchone()["n"] == len(chunks)
            cursor.execute(
                "SELECT chunk_id,predecessor_chunk_id FROM app.replay_chunk_source WHERE run_id=%s",
                (target,),
            )
            bindings = {row["chunk_id"]: row["predecessor_chunk_id"] for row in cursor.fetchall()}
        originals = {row["id"]: row for row in predecessor_chunks}
        for chunk in chunks:
            original = originals[bindings[chunk["id"]]]
            assert bindings.get(chunk["parent_id"]) == original["parent_id"]
            assert chunk["logical_chunk_key"] == original["logical_chunk_key"]
            assert chunk["plan_version"] == original["plan_version"]
            assert chunk["state"] == original["state"]
            assert chunk["reason"] == original["reason"] or chunk["leaf"]
        return {
            "predecessor_run_id": str(predecessor),
            "replay_run_id": str(target),
            "actual_cli_exit": 0,
            "input_kind": "replay",
            "upstream_denied": True,
            "temporal_split": True,
            "spatial_split": True,
            "topology_identical": True,
            "plan_nodes": len(chunks),
            "completed_leaves": sum(c["leaf"] for c in chunks),
            "scientific_no_change": True,
            "active_partition_no_change": True,
            "audit_attempts_increased": True,
            "active_generation_ids_before": baseline["active_generation_ids"],
            "active_generation_ids_after": replay["active_generation_ids"],
            "full_and_eligible_reconciliation_balanced": True,
            "attempt_increase": replay["after_at_report_snapshot"]["attempts"]
            - replay["before"]["attempts"],
            "audit_increase": replay["after_at_report_snapshot"]["audit_rows"]
            - replay["before"]["audit_rows"],
            "increase_explanation": "Replay creates a new run, fenced state/ticket events and "
            "recorded-origin landing attempts for each complete predecessor leaf; scientific "
            "no-ops reuse active generations. HTTP retries remain zero.",
            "before": replay["before"],
            "after": replay["after_at_report_snapshot"],
            "scope": "Synthetic complete plan, not live regional acceptance",
        }
    finally:
        ingestion.RequestOwner = original_request_owner
        ingestion.upstream_credential = original_credential
        cli.time = original_sleep_module
