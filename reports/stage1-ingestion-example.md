# Stage 1 persisted run report

Run: `4b95239d-c549-4305-9186-62ccd83beee2`. State: **partial**.

Reference UTC: `2025-04-01 00:00:00+00:00`. Frozen: True.

Scientific no change: False; active partitions no change: False.

Full/eligible reconciliation: True / True.

Coverage proved complete: False; gaps: 178.

Source policy S1-SOURCE-2: delivery_qualified_no_source_exclusions; source exclusions: 0; scientific source complete: unknown.

Counts distinguish payload attempts, profile occurrences and measurement levels.
DataFrame deep memory includes its index and is distinct from peak RSS.

Complete persisted evidence (including timings, reasons, availability, versions, raw references and measured storage comparisons):

```json
{
  "acceptance_status": "not_certified_by_this_report",
  "active_generation_ids": [
    "30ac0a35-7696-41f3-8683-55746ce9a498"
  ],
  "active_partition_no_change": false,
  "after_at_report_snapshot": {
    "active_generation_sha256": "05309646441137a5061734d1e4c07e4cada22b55fd12b311947bfc0873f29709",
    "active_partitions": 1,
    "attempts": 46,
    "audit_rows": 143,
    "floats": 1,
    "measurement_levels": 27,
    "profile_manifest_sha256": "712e064d3ef5bebe6dad9b68a7ec2c6b1b5ccfc8ad7481638fa23c16f3e67868",
    "profiles": 9,
    "runs": 9
  },
  "audit_and_attempt_rows_may_increase": true,
  "before": {
    "active_generation_sha256": "f1e37bd22075e849ec9b43481e9480d87a31da56e07fc44e6d188d6de8a08897",
    "active_partitions": 1,
    "attempts": 38,
    "audit_rows": 123,
    "floats": 1,
    "measurement_levels": 24,
    "profile_manifest_sha256": "f0ad6daaa180c897bd28171d157068f1d36548ea474f2be85eb63770d597a9fa",
    "profiles": 8,
    "reconciliation": {
      "full_snapshot": {
        "manifest_sha256": "f0ad6daaa180c897bd28171d157068f1d36548ea474f2be85eb63770d597a9fa",
        "measurement_levels": 24,
        "profiles": 8
      },
      "full_stored": {
        "manifest_sha256": "f0ad6daaa180c897bd28171d157068f1d36548ea474f2be85eb63770d597a9fa",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_snapshot": {
        "manifest_sha256": "f0ad6daaa180c897bd28171d157068f1d36548ea474f2be85eb63770d597a9fa",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_stored": {
        "manifest_sha256": "f0ad6daaa180c897bd28171d157068f1d36548ea474f2be85eb63770d597a9fa",
        "measurement_levels": 24,
        "profiles": 8
      }
    },
    "runs": 9
  },
  "cancellation_affected_unfinished_chunks": false,
  "chunks": [
    {
      "accounting": {
        "canonical_input_bytes": 4192,
        "inventory_verified": true,
        "known_source_levels": 3,
        "observed_profile_occurrences": 1,
        "raw_roles": {
          "inventory_after": "8492fac4-ae24-4236-89b3-7918dff8e05a",
          "inventory_before": "5cbebecf-087d-48ac-a164-fb28d95d0f29",
          "metadata": "845144ea-0d8b-41df-a0ae-d14f1eb50700",
          "profile": "e166b38f-150f-4f5d-bb36-20dba503d68b"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": null,
      "control_epoch": 2,
      "fence": 2,
      "id": "eaa66d33-f403-4f6f-807d-5830ae7f7820",
      "leaf": true,
      "logical_chunk_key": "1",
      "parent_id": null,
      "plan_version": "explicit-component-not-regional",
      "processing_claims": 1,
      "publication_attempts": 1,
      "reason": "deadline_expired",
      "requested_end": "2025-01-07 00:00:00+00:00",
      "requested_start": "2025-01-01 00:00:00+00:00",
      "state": "failed",
      "tile": {
        "height": 10,
        "south": 10,
        "west": 80,
        "width": 10
      }
    },
    {
      "accounting": {
        "canonical_input_bytes": 4192,
        "inventory_verified": true,
        "known_source_levels": 3,
        "observed_profile_occurrences": 1,
        "raw_roles": {
          "inventory_after": "5c050fb8-49f6-471c-aee6-519d68e92d88",
          "inventory_before": "e3d7ab05-8bd1-40a5-8728-f4cae322587c",
          "metadata": "37c7eb11-4549-42af-b008-69c635a608e1",
          "profile": "be5fd3bd-ce13-452c-9fb3-02ebcd9a970a"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": "2026-10-08 06:38:06.242386+00:00",
      "control_epoch": 2,
      "fence": 1,
      "id": "f4c7f197-bbe9-467e-b37b-795b64d91eea",
      "leaf": true,
      "logical_chunk_key": "0",
      "parent_id": null,
      "plan_version": "explicit-component-not-regional",
      "processing_claims": 1,
      "publication_attempts": 1,
      "reason": "verified_publication",
      "requested_end": "2025-01-07 00:00:00+00:00",
      "requested_start": "2025-01-01 00:00:00+00:00",
      "state": "complete",
      "tile": {
        "height": 10,
        "south": 10,
        "west": 70,
        "width": 10
      }
    }
  ],
  "closed": true,
  "comparison_scope": "Immutable finalization snapshot",
  "contract": "stage1-v3",
  "coverage": {
    "gaps": [
      "argovis/core/2025-01/20:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/20:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/20:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/30:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/30:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/40:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/40:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/50:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/50:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/60:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/60:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/70:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/70:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/80:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/80:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/90:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/90:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/100:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/100:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-60/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-50/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-40/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-30/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:-10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:0/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified",
      "argovis/core/2025-01/110:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:fetch_coverage",
      "argovis/core/2025-01/110:20/indian-ocean-v1/argovis-core-v1/scientific-json-v2:stored_empty_not_verified"
    ],
    "object_integrity_scope": "Verified at publication; a fresh selector byte check is required for present availability",
    "proved_complete": false,
    "requested": {
      "end": "2025-01-07T00:00:00+00:00",
      "geometry_sha256": "4378f043a9e3a10cf46f48367f7bfd6e417fb9c4534d180a016109db29db263f",
      "geometry_version": "indian-ocean-v1",
      "start": "2025-01-01T00:00:00+00:00"
    },
    "scope": "Full Indian Ocean request geometry at frozen commit snapshot; seeded component plans do not prove the region",
    "selectable_generation_ids": [
      "30ac0a35-7696-41f3-8683-55746ce9a498"
    ],
    "source_absence_evidence": [],
    "verified_empty_evidence": []
  },
  "environment_id": "00000000-0000-4000-8000-000000000003",
  "final_evidence_frozen": true,
  "full_snapshot_balanced": true,
  "kind": "persisted_ingestion_evidence",
  "leaf_count": 2,
  "occurrence_ledger_reconciliation": {
    "chunks_without_source_accounting": [],
    "ledger_known_source_levels": 6,
    "ledger_profile_occurrences": 2,
    "reported_known_source_levels": 6,
    "reported_received_profiles": 2,
    "scope": "Latest selection per leaf; ancestor/retry payload evidence is counted separately; absent accounting remains unknown"
  },
  "payload_accounting": [
    {
      "attempts": 8,
      "disposition": "verified_raw",
      "origin": "captured",
      "received_bytes": "0",
      "verified_json_bytes": "6154",
      "verified_payloads": 8
    }
  ],
  "persisted_metrics": {
    "active_generations": [
      {
        "bytes": 20182,
        "committed_at": "2026-10-08T06:38:06.239028+00:00",
        "generation": 9,
        "id": "30ac0a35-7696-41f3-8683-55746ce9a498",
        "levels": 27,
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "object_key": "normalised/sha256/0b930322253e9e2218bf76fd040721d1f001420eb054ba30de5b00dcf9ee1857.parquet",
        "profiles": 9,
        "sha256": "0b930322253e9e2218bf76fd040721d1f001420eb054ba30de5b00dcf9ee1857",
        "verification_evidence": {
          "membership_sha256": "4b16c455837aa702c9d527ee596dde8511df8029f33221065df179ba69fd8c1f",
          "profiles": 9,
          "rows": 27,
          "schema_sha256": "265e6149cab7be216f5b87228bd67fdd1ab3cad8cd807bea328b8ff7bdc88c80",
          "storage_comparison": {
            "availability": {
              "pressure": {
                "_adjusted": 27,
                "_adjusted_qc": 27,
                "_error": 0,
                "_original_error": 0,
                "_qc": 0,
                "original": 0
              },
              "salinity": {
                "_adjusted": 27,
                "_adjusted_qc": 27,
                "_error": 0,
                "_original_error": 0,
                "_qc": 0,
                "original": 0
              },
              "temperature": {
                "_adjusted": 27,
                "_adjusted_qc": 27,
                "_error": 0,
                "_original_error": 0,
                "_qc": 0,
                "original": 0
              }
            },
            "columns": [
              "profile_id",
              "source_profile_id",
              "profile_hash",
              "profile_content",
              "canonical_level",
              "level_index",
              "pressure",
              "pressure_adjusted",
              "pressure_error",
              "pressure_original_error",
              "pressure_qc",
              "pressure_adjusted_qc",
              "pressure_qc_source",
              "pressure_adjusted_qc_source",
              "pressure_unit",
              "pressure_unit_source",
              "pressure_data_mode",
              "pressure_flags",
              "temperature",
              "temperature_adjusted",
              "temperature_error",
              "temperature_original_error",
              "temperature_qc",
              "temperature_adjusted_qc",
              "temperature_qc_source",
              "temperature_adjusted_qc_source",
              "temperature_unit",
              "temperature_unit_source",
              "temperature_data_mode",
              "temperature_flags",
              "salinity",
              "salinity_adjusted",
              "salinity_error",
              "salinity_original_error",
              "salinity_qc",
              "salinity_adjusted_qc",
              "salinity_qc_source",
              "salinity_adjusted_qc_source",
              "salinity_unit",
              "salinity_unit_source",
              "salinity_data_mode",
              "salinity_flags"
            ],
            "equivalence": "Same ordered typed IPC rows supplied to the writer; complete Parquet scientific/hash/scalar verification before measurement",
            "index": "RangeIndex",
            "index_included": true,
            "memory_scope": "Logical DataFrame deep memory; distinct from process RSS",
            "nullable_dtypes": {
              "canonical_level": "string[pyarrow]",
              "level_index": "int32[pyarrow]",
              "pressure": "double[pyarrow]",
              "pressure_adjusted": "double[pyarrow]",
              "pressure_adjusted_qc": "string[pyarrow]",
              "pressure_adjusted_qc_source": "string[pyarrow]",
              "pressure_data_mode": "string[pyarrow]",
              "pressure_error": "double[pyarrow]",
              "pressure_flags": "list<element: string>[pyarrow]",
              "pressure_original_error": "double[pyarrow]",
              "pressure_qc": "string[pyarrow]",
              "pressure_qc_source": "string[pyarrow]",
              "pressure_unit": "string[pyarrow]",
              "pressure_unit_source": "string[pyarrow]",
              "profile_content": "string[pyarrow]",
              "profile_hash": "string[pyarrow]",
              "profile_id": "string[pyarrow]",
              "salinity": "double[pyarrow]",
              "salinity_adjusted": "double[pyarrow]",
              "salinity_adjusted_qc": "string[pyarrow]",
              "salinity_adjusted_qc_source": "string[pyarrow]",
              "salinity_data_mode": "string[pyarrow]",
              "salinity_error": "double[pyarrow]",
              "salinity_flags": "list<element: string>[pyarrow]",
              "salinity_original_error": "double[pyarrow]",
              "salinity_qc": "string[pyarrow]",
              "salinity_qc_source": "string[pyarrow]",
              "salinity_unit": "string[pyarrow]",
              "salinity_unit_source": "string[pyarrow]",
              "source_profile_id": "string[pyarrow]",
              "temperature": "double[pyarrow]",
              "temperature_adjusted": "double[pyarrow]",
              "temperature_adjusted_qc": "string[pyarrow]",
              "temperature_adjusted_qc_source": "string[pyarrow]",
              "temperature_data_mode": "string[pyarrow]",
              "temperature_error": "double[pyarrow]",
              "temperature_flags": "list<element: string>[pyarrow]",
              "temperature_original_error": "double[pyarrow]",
              "temperature_qc": "string[pyarrow]",
              "temperature_qc_source": "string[pyarrow]",
              "temperature_unit": "string[pyarrow]",
              "temperature_unit_source": "string[pyarrow]"
            },
            "pandas_deep_memory_bytes": 59103,
            "pandas_to_parquet_ratio": 2.928500644138341,
            "pandas_version": "2.3.3",
            "parquet_bytes": 20182,
            "parquet_index": "source level_index; pandas RangeIndex not stored",
            "pyarrow_version": "23.0.1",
            "ratio_status": "measured",
            "rows": 27
          },
          "writer_options": {
            "compression": "zstd",
            "compression_level": 3,
            "data_page_size": 65536,
            "store_schema": true,
            "use_dictionary": [
              "profile_id",
              "source_profile_id",
              "profile_hash",
              "profile_content"
            ],
            "version": "2.6",
            "write_batch_size": 64,
            "write_statistics": true
          }
        },
        "verified_at": "2026-10-08T06:38:05.956204+00:00",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      }
    ],
    "attempt_reasons": [
      {
        "attempts": 8,
        "disposition": "verified_raw",
        "error_category": null,
        "http_status": 200,
        "origin": "captured"
      }
    ],
    "attempt_timing": [
      {
        "attempts": 8,
        "disposition": "verified_raw",
        "elapsed_seconds_max": 0.090963,
        "elapsed_seconds_sum": 0.522956,
        "first_started_at": "2026-10-08T06:38:05.069354+00:00",
        "last_finished_at": "2026-10-08T06:38:05.402534+00:00",
        "origin": "captured",
        "unfinished_attempts": 0
      }
    ],
    "availability": {
      "full_retained": {
        "pressure": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        },
        "salinity": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        },
        "temperature": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        }
      },
      "run_eligible": {
        "pressure": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        },
        "salinity": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        },
        "temperature": {
          "_adjusted": 27,
          "_adjusted_qc": 27,
          "_error": 0,
          "_original_error": 0,
          "_qc": 0,
          "original": 0
        }
      }
    },
    "catalogue_slot_versions": {
      "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2": 9,
      "argovis/core/2025-01/80:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2": 0
    },
    "coverage_receipt_count": 9,
    "coverage_receipts": [
      {
        "committed_at": "2026-10-08T06:38:06.241042+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "1556614a-482d-40da-bab6-1107ca138f97",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 9,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:37:16.247228+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "1b10313b-e45c-4256-a073-664e9f0e7c6e",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 6,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:37:36.458419+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "2ebbe6c9-c021-4387-8d06-bf0a1fe2cd32",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 7,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:37:56.415422+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "50def8e4-409e-4d7e-a94c-88058ab64809",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 8,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:36:24.181739+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "7bdce373-a821-4ef8-85fd-b73972c75178",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 4,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:35:54.190373+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "a6f43003-777a-4830-b6cc-27006a6ab9a9",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 3,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:36:54.442649+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "a7fb2e3e-0d12-4db3-8916-b89f7b0f30eb",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 5,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:35:24.094032+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "bd250564-757e-4a64-a9ca-9a63cd19eb1c",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 2,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      },
      {
        "committed_at": "2026-10-08T06:34:54.710011+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "c6551c50-2e4b-4c75-8057-ecbdfc5bdd7d",
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "requested_end": "2025-01-07T00:00:00+00:00",
        "requested_start": "2025-01-01T00:00:00+00:00",
        "slot_version": 1,
        "stored_disposition": "active_generation",
        "tile": {
          "height": 10,
          "south": 10,
          "west": 70,
          "width": 10
        }
      }
    ],
    "http_retries": 0,
    "invalid_scientific_header_profiles": 0,
    "limits": {
      "canonical_run_bytes": 42949672960,
      "contract": "stage1-v3",
      "execution_seconds": 90,
      "plan_version": "indian-ocean-plan-v2",
      "source_policy": "S1-SOURCE-2"
    },
    "phase_timings": [
      {
        "episodes": 1,
        "phase": "complete",
        "wall_seconds_sum": 28.836801
      },
      {
        "episodes": 1,
        "phase": "failed",
        "wall_seconds_sum": 0.005417
      },
      {
        "episodes": 2,
        "phase": "fetching",
        "wall_seconds_sum": 0.645322
      },
      {
        "episodes": 2,
        "phase": "landed",
        "wall_seconds_sum": 0.014924
      },
      {
        "episodes": 2,
        "phase": "planned",
        "wall_seconds_sum": 0.231012
      },
      {
        "episodes": 2,
        "phase": "publishing",
        "wall_seconds_sum": 30.333782
      },
      {
        "episodes": 2,
        "phase": "validating",
        "wall_seconds_sum": 0.168499
      }
    ],
    "policy_versions": {
      "geometry": "indian-ocean-v1",
      "hash": "scientific-json-v2",
      "mapping": "argovis-core-v1",
      "qc": "core-good-v1",
      "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
      "specification": "2.36.2",
      "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
      "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
      "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
    },
    "processing_recoveries": 0,
    "replacement_levels": {
      "inserted_replacement_levels": 3,
      "no_op_levels": 0,
      "old_levels_removed": 0,
      "stale_skipped_levels": 0
    },
    "requested": {
      "end": "2025-01-07T00:00:00+00:00",
      "geometry_sha256": "4378f043a9e3a10cf46f48367f7bfd6e417fb9c4534d180a016109db29db263f",
      "geometry_version": "indian-ocean-v1",
      "start": "2025-01-01T00:00:00+00:00"
    },
    "resource_counters": {
      "accepted_insert_replacement_levels": 3,
      "accepted_new_profiles": 1,
      "canonical_bytes": 167680,
      "controller_claims": 2,
      "http_attempts": 0,
      "received_bytes": 0
    },
    "resource_limits": [],
    "run_timing": {
      "created_actual_utc": "2026-10-08T06:37:58.333392+00:00",
      "elapsed_seconds": 36.746,
      "terminal_event_actual_utc": "2026-10-08T06:38:35.079392+00:00"
    },
    "selected_profiles_by_slot": {
      "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2": 9
    },
    "source_attribution": {
      "argo_doi": "https://doi.org/10.17882/42182",
      "argovis_contract_citation": "https://zenodo.org/records/15708506",
      "input_kind": "captured",
      "provider": "International Argo Program and national contributors, via Argovis",
      "scope": "Attribution is not proof of live capture; raw provenance distinguishes synthetic inputs",
      "terms_and_acknowledgement": "https://argo.ucsd.edu/data/acknowledging-argo/"
    },
    "state_reasons": [
      {
        "events": 1,
        "new_state": "complete",
        "reason": "verified_publication"
      },
      {
        "events": 1,
        "new_state": "failed",
        "reason": "deadline_expired"
      },
      {
        "events": 1,
        "new_state": "fetching",
        "reason": "child_phase"
      },
      {
        "events": 2,
        "new_state": "fetching",
        "reason": "worker_started"
      },
      {
        "events": 2,
        "new_state": "landed",
        "reason": "child_phase"
      },
      {
        "events": 2,
        "new_state": "landed",
        "reason": "complete_verified_landing"
      },
      {
        "events": 1,
        "new_state": "partial",
        "reason": "deadline_expired"
      },
      {
        "events": 2,
        "new_state": "planned",
        "reason": "processing_claim"
      },
      {
        "events": 1,
        "new_state": "publishing",
        "reason": "child_phase"
      },
      {
        "events": 2,
        "new_state": "publishing",
        "reason": "validated_candidate"
      },
      {
        "events": 2,
        "new_state": "validating",
        "reason": "child_phase"
      },
      {
        "events": 2,
        "new_state": "validating",
        "reason": "mapping_started"
      },
      {
        "events": 1,
        "new_state": null,
        "reason": "controller_adoption"
      },
      {
        "events": 1,
        "new_state": null,
        "reason": "run_admitted_reference_captured"
      }
    ],
    "unknown_level_reasons": [],
    "verified_raw_provenance": [
      {
        "application_commit": "offline-broker-proof",
        "bytes": 360,
        "endpoint_path": "/argo/meta",
        "id": "37c7eb11-4549-42af-b008-69c635a608e1",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-08T06:37:58.313668+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.377770+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "5c050fb8-49f6-471c-aee6-519d68e92d88",
        "logical_request_sha256": "c86e454265521caaef56fe1235b06dcd4c572c12fd70b7d31aeec8085f6f2353",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.310977+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.313586+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "5cbebecf-087d-48ac-a164-fb28d95d0f29",
        "logical_request_sha256": "7830f50cf0f7d2638d4742f9fd54659dd056448b2e753c8b7fb29ea2229fc293",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.311955+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.185262+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 360,
        "endpoint_path": "/argo/meta",
        "id": "845144ea-0d8b-41df-a0ae-d14f1eb50700",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-08T06:37:58.313668+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.393369+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "8492fac4-ae24-4236-89b3-7918dff8e05a",
        "logical_request_sha256": "6aa435adb370fedc8032a70db4c6e581a73a039efdb96bd62cacbefad63e742f",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.313532+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.333342+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 975,
        "endpoint_path": "/argo",
        "id": "be5fd3bd-ce13-452c-9fb3-02ebcd9a970a",
        "logical_request_sha256": "f6f66b2fb3bb5217d19bd77717ed29ac8a6bc05571a81d29fbc795b7f3f142ba",
        "object_key": "raw/sha256/0a55d70bc1beac31d5d561305cee614ca004f0a26405adac970241b7317ee39c.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.310381+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.236290+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "0a55d70bc1beac31d5d561305cee614ca004f0a26405adac970241b7317ee39c",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 975,
        "endpoint_path": "/argo",
        "id": "e166b38f-150f-4f5d-bb36-20dba503d68b",
        "logical_request_sha256": "68175debe81fb3860b667fec6e3499a32cb34059bfcc87559da2ee674dff3aa2",
        "object_key": "raw/sha256/e1004098695855dec96be5c3833ecb1951fae0098618f3c18a55aa96caaa92b4.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.312825+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.267568+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "e1004098695855dec96be5c3833ecb1951fae0098618f3c18a55aa96caaa92b4",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      },
      {
        "application_commit": "offline-broker-proof",
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "e3d7ab05-8bd1-40a5-8728-f4cae322587c",
        "logical_request_sha256": "6729ab7a2212e7692bf4d9f48474ced9123bb7741191b8263b6cb2e212b64dcc",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T06:37:58.309698+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T06:38:05.152677+00:00",
          "urls_scrubbed": 0,
          "validation": {
            "documents": 1,
            "schema": "argovis-core-2.36.2+ifremer-fluorescence-v1-object-array"
          },
          "version": "raw-sanitization-v1"
        },
        "sha256": "5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48",
        "versions": {
          "geometry": "indian-ocean-v1",
          "hash": "scientific-json-v2",
          "mapping": "argovis-core-v1",
          "qc": "core-good-v1",
          "source_contract": "argovis-core-2.36.2+ifremer-fluorescence-v1",
          "specification": "2.36.2",
          "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
          "translator_revision": "cbf2bb48ed5d95532c18bb2cd5217e44618356cf",
          "translator_sha256": "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
        }
      }
    ]
  },
  "profile_and_measurement_accounting": [
    {
      "committed": false,
      "known_measurement_levels": 3,
      "leaf": true,
      "outcome": "blocked_uncommitted",
      "profile_occurrences": 1,
      "unknown_level_profiles": 0
    },
    {
      "committed": true,
      "known_measurement_levels": 3,
      "leaf": true,
      "outcome": "insert",
      "profile_occurrences": 1,
      "unknown_level_profiles": 0
    }
  ],
  "reconciliation_populations": {
    "full_snapshot": {
      "manifest_sha256": "712e064d3ef5bebe6dad9b68a7ec2c6b1b5ccfc8ad7481638fa23c16f3e67868",
      "measurement_levels": 27,
      "profiles": 9
    },
    "full_stored": {
      "manifest_sha256": "712e064d3ef5bebe6dad9b68a7ec2c6b1b5ccfc8ad7481638fa23c16f3e67868",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_snapshot": {
      "manifest_sha256": "712e064d3ef5bebe6dad9b68a7ec2c6b1b5ccfc8ad7481638fa23c16f3e67868",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_stored": {
      "manifest_sha256": "712e064d3ef5bebe6dad9b68a7ec2c6b1b5ccfc8ad7481638fa23c16f3e67868",
      "measurement_levels": 27,
      "profiles": 9
    }
  },
  "reference_time_utc": "2025-04-01 00:00:00+00:00",
  "run_eligible_balanced": true,
  "run_id": "4b95239d-c549-4305-9186-62ccd83beee2",
  "scientific_level_delta_balanced": true,
  "scientific_no_change": false,
  "snapshot_evidence_scope": "Committed membership and persisted Parquet verification; this report does not replace a fresh byte-integrity selector check.",
  "source_policy": {
    "acceptance_qualification": "delivery_qualified_no_source_exclusions",
    "empty_delivery_receipts_by_role": {},
    "policy": "S1-SOURCE-2",
    "population": "eligible structurally valid profiles delivered by the pinned Argovis selection interface; not a census of underlying Argo/GDAC inputs",
    "scientific_source_complete": "unknown",
    "source_exclusion_count": 0,
    "source_exclusions": []
  },
  "state": "partial",
  "terminal_leaves": 2,
  "termination_reason": "deadline_expired"
}
```
