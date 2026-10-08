"""Bounded reports from persisted evidence, with no inferred acceptance pass."""

import json
import time
import uuid
from typing import Any

from .coverage import Receipt, resolve
from .objects import CatalogueRecord
from .planning import Interval, Tile, timestamp
from .repository import Repository


def coverage_evidence(metrics: dict[str, Any], environment: uuid.UUID) -> dict[str, Any]:
    """Pure selection proof from a frozen committed catalogue snapshot."""
    requested = metrics["requested"]
    if metrics["coverage_receipt_count"] > 16384:
        return {"gaps": ["coverage_evidence_limit"], "proved_complete": False}
    records = tuple(
        CatalogueRecord(
            uuid.UUID(row["id"]),
            environment,
            row["logical_key"],
            row["generation"],
            metrics["catalogue_slot_versions"][row["logical_key"]],
            "active",
            True,
            True,
            "indian-ocean-v1",
            "core-parquet-v1",
            row["object_key"],
            row["sha256"],
            row["bytes"],
        )
        for row in metrics["active_generations"]
    )
    receipts = tuple(
        Receipt(
            uuid.UUID(row["id"]),
            Interval(timestamp(row["requested_start"]), timestamp(row["requested_end"])),
            Tile(**row["tile"]),
            row["logical_key"],
            row["slot_version"],
            row["fetch_disposition"],
            row["stored_disposition"],
            row["committed_at"],
        )
        for row in metrics["coverage_receipts"]
    )
    selection = resolve(
        Interval(timestamp(requested["start"]), timestamp(requested["end"])),
        records,
        metrics["catalogue_slot_versions"],
        receipts,
        lambda interval, slot: metrics["selected_profiles_by_slot"].get(slot, 0),
        deadline=time.monotonic() + 60,
    )
    return {
        "requested": requested,
        "gaps": list(selection.gaps),
        "proved_complete": not selection.gaps,
        "selectable_generation_ids": [str(row.partition_id) for row in selection.records],
        "verified_empty_evidence": list(selection.empty_evidence),
        "source_absence_evidence": list(selection.source_absence_evidence),
        "scope": "Full Indian Ocean request geometry at frozen commit snapshot; "
        "seeded component plans do not prove the region",
        "object_integrity_scope": "Verified at publication; a fresh selector byte check "
        "is required for present availability",
    }


def persisted_report(repository: Repository, run: uuid.UUID) -> dict[str, Any]:
    with repository.transaction(readonly_snapshot=True) as cursor:
        cursor.execute("SELECT * FROM app.ingestion_run WHERE id=%s", (run,))
        control = cursor.fetchone()
        if control is None:
            from .numeric import Rejection

            raise Rejection("unknown_run")
        cursor.execute("SELECT evidence FROM app.run_baseline WHERE run_id=%s", (run,))
        baseline = cursor.fetchone()
        cursor.execute("SELECT evidence FROM app.run_final_evidence WHERE run_id=%s", (run,))
        final = cursor.fetchone()
        if final is None:
            cursor.execute("SELECT app.scientific_snapshot() AS evidence")
            current = cursor.fetchone()["evidence"]
            cursor.execute("SELECT app.reconciliation_snapshot(%s) AS evidence", (run,))
            populations = cursor.fetchone()["evidence"]
        else:
            current = final["evidence"]["science"]
            populations = final["evidence"]["reconciliation"]
        if final is None:
            cursor.execute("SELECT app.report_metrics_snapshot(%s) AS evidence", (run,))
            metrics = cursor.fetchone()["evidence"]
            cursor.execute("SELECT to_regprocedure('app.resource_limit_snapshot(uuid)') AS fn")
            if cursor.fetchone()["fn"] is not None:
                cursor.execute("SELECT app.resource_limit_snapshot(%s) AS evidence", (run,))
                metrics["resource_limits"] = cursor.fetchone()["evidence"]
        else:
            metrics = final["evidence"]["report_metrics"]
        cursor.execute(
            "SELECT c.id,c.state,c.leaf,c.parent_id,c.logical_chunk_key,c.plan_version,"
            "c.requested_start,c.requested_end,c.tile,c.fence,c.control_epoch,"
            "c.processing_claims,c.publication_attempts,c.reason,c.completed_at,"
            "a.evidence AS accounting FROM app.ingestion_chunk c "
            "LEFT JOIN app.chunk_accounting a ON a.chunk_id=c.id "
            "WHERE c.run_id=%s ORDER BY c.id LIMIT 16385",
            (run,),
        )
        chunks = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT a.origin,a.disposition,count(*) AS attempts,"
            "sum(a.bytes_received) AS received_bytes,count(m.id) AS verified_payloads,"
            "coalesce(sum(m.bytes),0) AS verified_json_bytes "
            "FROM app.ingestion_attempt a JOIN app.ingestion_chunk c ON c.id=a.chunk_id "
            "LEFT JOIN app.raw_manifest m ON m.attempt_id=a.id WHERE c.run_id=%s "
            "GROUP BY a.origin,a.disposition ORDER BY a.origin,a.disposition",
            (run,),
        )
        payloads = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT c.leaf,o.outcome,o.committed,count(*) AS profile_occurrences,"
            "coalesce(sum(o.source_levels),0) AS known_measurement_levels,"
            "count(*) FILTER(WHERE o.source_levels IS NULL) AS unknown_level_profiles "
            "FROM app.profile_outcome o JOIN app.ingestion_chunk c ON c.id=o.chunk_id "
            "WHERE c.run_id=%s GROUP BY c.leaf,o.outcome,o.committed "
            "ORDER BY c.leaf,o.outcome,o.committed",
            (run,),
        )
        outcomes = [dict(row) for row in cursor.fetchall()]
        # to_jsonb keeps this readable on pre-0009 databases without http_status.
        cursor.execute(
            "SELECT a.role,count(*) AS receipts FROM app.raw_manifest m "
            "JOIN app.ingestion_attempt a ON a.id=m.attempt_id "
            "WHERE m.run_id=%s AND to_jsonb(m)->>'http_status'='404' "
            "GROUP BY a.role ORDER BY a.role",
            (run,),
        )
        empty_receipts = {row["role"]: row["receipts"] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT o.chunk_id,o.occurrence_index,o.source_levels,o.evidence "
            "FROM app.profile_outcome o JOIN app.ingestion_chunk c ON c.id=o.chunk_id "
            "WHERE c.run_id=%s AND c.leaf AND o.outcome='excluded_source_loss' "
            "ORDER BY o.chunk_id,o.occurrence_index LIMIT 100001",
            (run,),
        )
        exclusions = [
            {
                "chunk_id": str(row["chunk_id"]),
                "occurrence_index": row["occurrence_index"],
                "returned_levels": row["source_levels"],
                **row["evidence"],
            }
            for row in cursor.fetchall()
        ]
        empty = {
            "profiles": 0,
            "measurement_levels": 0,
            "manifest_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        }
        for scope in (
            "full_stored",
            "full_snapshot",
            "run_eligible_stored",
            "run_eligible_snapshot",
        ):
            populations.setdefault(scope, dict(empty))
        cancellation_affected = control["cancellation_affected"]
    before = None if baseline is None else baseline["evidence"]
    scientific_keys = ("floats", "profiles", "measurement_levels", "profile_manifest_sha256")
    active_keys = ("active_partitions", "active_generation_sha256")
    result = {
        "kind": "persisted_ingestion_evidence",
        "contract": "stage1-v3",
        "run_id": str(run),
        "environment_id": str(control["environment_id"]),
        "state": control["state"],
        "closed": control["closed"],
        "termination_reason": control["termination_reason"],
        "reference_time_utc": control["run_reference_time_utc"],
        "before": before,
        "after_at_report_snapshot": current,
        "final_evidence_frozen": final is not None,
        "scientific_no_change": None
        if before is None
        else all(before[key] == current[key] for key in scientific_keys),
        "active_partition_no_change": None
        if before is None
        else all(before[key] == current[key] for key in active_keys),
        "audit_and_attempt_rows_may_increase": True,
        "cancellation_affected_unfinished_chunks": cancellation_affected,
        "reconciliation_populations": populations,
        "full_snapshot_balanced": populations["full_stored"] == populations["full_snapshot"],
        "run_eligible_balanced": populations["run_eligible_stored"]
        == populations["run_eligible_snapshot"],
        "snapshot_evidence_scope": "Committed membership and persisted Parquet verification; "
        "this report does not replace a fresh byte-integrity selector check.",
        "payload_accounting": payloads,
        "profile_and_measurement_accounting": outcomes,
        "chunks": chunks,
        "terminal_leaves": sum(
            row["leaf"] and row["state"] in ("complete", "quarantined", "failed") for row in chunks
        ),
        "leaf_count": sum(row["leaf"] for row in chunks),
        "acceptance_status": "not_certified_by_this_report",
        "comparison_scope": "Immutable finalization snapshot"
        if final is not None
        else "Open-run current snapshot; provisional evidence only",
    }
    result["persisted_metrics"] = metrics
    result["coverage"] = coverage_evidence(metrics, control["environment_id"])
    # S1-SOURCE-2: qualified delivery population. Exclusions are never renamed
    # quarantine successes, and zero exclusions does not prove source completeness.
    result["source_policy"] = {
        "policy": "S1-SOURCE-2",
        "population": "eligible structurally valid profiles delivered by the pinned "
        "Argovis selection interface; not a census of underlying Argo/GDAC inputs",
        "empty_delivery_receipts_by_role": empty_receipts,
        "source_exclusions": exclusions,
        "source_exclusion_count": len(exclusions),
        "acceptance_qualification": "acceptance_qualified_with_source_exclusions"
        if exclusions
        else "delivery_qualified_no_source_exclusions",
        "scientific_source_complete": False if exclusions else "unknown",
    }
    result["active_generation_ids"] = [row["id"] for row in metrics["active_generations"]]
    result["scientific_level_delta_balanced"] = (
        None
        if before is None
        else (
            before["measurement_levels"]
            - metrics["replacement_levels"]["old_levels_removed"]
            + metrics["replacement_levels"]["inserted_replacement_levels"]
            == current["measurement_levels"]
        )
    )
    leaf_accounting = [
        row["accounting"] for row in chunks if row["leaf"] and row["accounting"] is not None
    ]
    result["occurrence_ledger_reconciliation"] = {
        "reported_received_profiles": sum(
            row["observed_profile_occurrences"] for row in leaf_accounting
        ),
        "ledger_profile_occurrences": sum(
            row["profile_occurrences"] for row in outcomes if row["leaf"]
        ),
        "reported_known_source_levels": sum(row["known_source_levels"] for row in leaf_accounting),
        "ledger_known_source_levels": sum(
            row["known_measurement_levels"] for row in outcomes if row["leaf"]
        ),
        "chunks_without_source_accounting": [
            str(row["id"]) for row in chunks if row["leaf"] and row["accounting"] is None
        ],
        "scope": "Latest selection per leaf; ancestor/retry payload evidence is counted "
        "separately; absent accounting remains unknown",
    }
    return result


def markdown_report(report: dict[str, Any]) -> str:
    """All numbers originate in the supplied persisted snapshot, never worker RAM."""
    lines = [
        "# Stage 1 persisted run report",
        "",
        f"Run: `{report['run_id']}`. State: **{report['state']}**.",
        "",
        f"Reference UTC: `{report['reference_time_utc']}`. "
        f"Frozen: {report['final_evidence_frozen']}.",
        "",
        f"Scientific no change: {report['scientific_no_change']}; "
        f"active partitions no change: {report['active_partition_no_change']}.",
        "",
        f"Full/eligible reconciliation: {report['full_snapshot_balanced']} / "
        f"{report['run_eligible_balanced']}.",
        "",
        f"Coverage proved complete: {report['coverage']['proved_complete']}; "
        f"gaps: {len(report['coverage']['gaps'])}.",
        "",
        f"Source policy {report['source_policy']['policy']}: "
        f"{report['source_policy']['acceptance_qualification']}; source exclusions: "
        f"{report['source_policy']['source_exclusion_count']}; scientific source complete: "
        f"{report['source_policy']['scientific_source_complete']}.",
        "",
        "Counts distinguish payload attempts, profile occurrences and measurement levels.",
        "DataFrame deep memory includes its index and is distinct from peak RSS.",
        "",
        "Complete persisted evidence (including timings, reasons, availability, versions, "
        "raw references and measured storage comparisons):",
        "",
        "```json",
        json.dumps(report, default=str, sort_keys=True, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)
