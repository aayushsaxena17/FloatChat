# Stage 1 persisted run report

Run: `70915a4a-e3fe-41e8-9d6b-a4d35b190cfe`. State: **partial**.

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
    "5267bdf3-89c1-41fd-84cd-e0a1eff9230f"
  ],
  "active_partition_no_change": false,
  "after_at_report_snapshot": {
    "active_generation_sha256": "e4bc8bc64964337be5408d514c8d6bd920501528e0457596d891da4e5f96ae1d",
    "active_partitions": 1,
    "attempts": 46,
    "audit_rows": 143,
    "floats": 1,
    "measurement_levels": 27,
    "profile_manifest_sha256": "d539955654fac1a7fa0ed012abd553baad03f07430a5777cb8576b0fe8cf27d4",
    "profiles": 9,
    "runs": 9
  },
  "audit_and_attempt_rows_may_increase": true,
  "before": {
    "active_generation_sha256": "1d3ed4677bebe1f963be90cc4c7fb74008f53040118b44e2162a04eb9fc3afd5",
    "active_partitions": 1,
    "attempts": 38,
    "audit_rows": 123,
    "floats": 1,
    "measurement_levels": 24,
    "profile_manifest_sha256": "dfeec773d4f90cffb3b1b98243cbbccd2e4795ae554c882b8524c2ff3be5652e",
    "profiles": 8,
    "reconciliation": {
      "full_snapshot": {
        "manifest_sha256": "dfeec773d4f90cffb3b1b98243cbbccd2e4795ae554c882b8524c2ff3be5652e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "full_stored": {
        "manifest_sha256": "dfeec773d4f90cffb3b1b98243cbbccd2e4795ae554c882b8524c2ff3be5652e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_snapshot": {
        "manifest_sha256": "dfeec773d4f90cffb3b1b98243cbbccd2e4795ae554c882b8524c2ff3be5652e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_stored": {
        "manifest_sha256": "dfeec773d4f90cffb3b1b98243cbbccd2e4795ae554c882b8524c2ff3be5652e",
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
          "inventory_after": "d004b825-5ffb-458f-b643-09dd23679cc0",
          "inventory_before": "3473b51d-80e1-4294-a873-bcd8861bc5c2",
          "metadata": "8b2a077f-6ab3-4a72-b2fb-4c2bd19d66e6",
          "profile": "cbbbb0ab-f415-47e6-9857-622c85893914"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": null,
      "control_epoch": 2,
      "fence": 2,
      "id": "2c574d6f-46fa-4179-b3eb-17cd51bec8d8",
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
          "inventory_after": "d142a1fa-5adb-4538-9d53-a152b8ec25b4",
          "inventory_before": "096d6fc0-0808-4da8-bcd7-8d0157f1e793",
          "metadata": "aab8800f-fd7a-4cbf-884e-b057eac71cfa",
          "profile": "59bb20a7-f962-4c40-927e-0272cb2ab1b4"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": "2026-10-08 11:32:18.181258+00:00",
      "control_epoch": 2,
      "fence": 1,
      "id": "4b77f91f-4a7a-4d88-9949-fcaf60014100",
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
      "5267bdf3-89c1-41fd-84cd-e0a1eff9230f"
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
        "bytes": 20179,
        "committed_at": "2026-10-08T11:32:18.177177+00:00",
        "generation": 9,
        "id": "5267bdf3-89c1-41fd-84cd-e0a1eff9230f",
        "levels": 27,
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "object_key": "normalised/sha256/1d068ee933778e124984299662f2dec20f8c5403e45e36a4fd1fba53e7f705a8.parquet",
        "profiles": 9,
        "sha256": "1d068ee933778e124984299662f2dec20f8c5403e45e36a4fd1fba53e7f705a8",
        "verification_evidence": {
          "membership_sha256": "17e0b72afab3550830de8506e6fec321b8dc6a3e4b95b692e9c022918ec90d29",
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
            "pandas_to_parquet_ratio": 2.92893602259775,
            "pandas_version": "2.3.3",
            "parquet_bytes": 20179,
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
        "verified_at": "2026-10-08T11:32:18.086009+00:00",
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
        "elapsed_seconds_max": 0.03551,
        "elapsed_seconds_sum": 0.233923,
        "first_started_at": "2026-10-08T11:32:17.731167+00:00",
        "last_finished_at": "2026-10-08T11:32:17.894007+00:00",
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
        "committed_at": "2026-10-08T11:30:06.475695+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "21caebb2-1695-4ceb-b1fc-ed56c3032c79",
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
        "committed_at": "2026-10-08T11:29:36.635937+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "5d5389df-b4b2-4dc8-b437-b492e3c3d88c",
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
        "committed_at": "2026-10-08T11:32:08.366558+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "78e9c97e-c992-4329-b46c-a059618483e4",
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
        "committed_at": "2026-10-08T11:31:48.240411+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "7bcfc4d2-7945-43f4-946d-fc3bee16c6f8",
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
        "committed_at": "2026-10-08T11:31:28.058071+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "be861276-8306-46e3-890b-344fa620df73",
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
        "committed_at": "2026-10-08T11:31:06.190071+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "cb824a44-9b05-4005-ad3e-b00a759910df",
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
        "committed_at": "2026-10-08T11:30:36.303803+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "d045af80-d73a-4b22-8670-55b72cf9275e",
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
        "committed_at": "2026-10-08T11:32:18.17848+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "dbd6d651-da64-4976-bb67-938bcb95b0b2",
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
        "committed_at": "2026-10-08T11:29:07.100391+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "e6d041d4-c096-4c0b-89ea-e406201edfc4",
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
        "wall_seconds_sum": 29.375046
      },
      {
        "episodes": 1,
        "phase": "failed",
        "wall_seconds_sum": 0.002106
      },
      {
        "episodes": 2,
        "phase": "fetching",
        "wall_seconds_sum": 0.288412
      },
      {
        "episodes": 2,
        "phase": "landed",
        "wall_seconds_sum": 0.006115
      },
      {
        "episodes": 2,
        "phase": "planned",
        "wall_seconds_sum": 0.142484
      },
      {
        "episodes": 2,
        "phase": "publishing",
        "wall_seconds_sum": 29.895628
      },
      {
        "episodes": 2,
        "phase": "validating",
        "wall_seconds_sum": 0.070995
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
      "created_actual_utc": "2026-10-08T11:32:09.981183+00:00",
      "elapsed_seconds": 37.575206,
      "terminal_event_actual_utc": "2026-10-08T11:32:47.556389+00:00"
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
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "096d6fc0-0808-4da8-bcd7-8d0157f1e793",
        "logical_request_sha256": "6729ab7a2212e7692bf4d9f48474ced9123bb7741191b8263b6cb2e212b64dcc",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.978253+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.763406+00:00",
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
        "id": "3473b51d-80e1-4294-a873-bcd8861bc5c2",
        "logical_request_sha256": "7830f50cf0f7d2638d4742f9fd54659dd056448b2e753c8b7fb29ea2229fc293",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.97909+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.789239+00:00",
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
        "id": "59bb20a7-f962-4c40-927e-0272cb2ab1b4",
        "logical_request_sha256": "f6f66b2fb3bb5217d19bd77717ed29ac8a6bc05571a81d29fbc795b7f3f142ba",
        "object_key": "raw/sha256/0a55d70bc1beac31d5d561305cee614ca004f0a26405adac970241b7317ee39c.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.978461+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.799653+00:00",
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
        "bytes": 360,
        "endpoint_path": "/argo/meta",
        "id": "8b2a077f-6ab3-4a72-b2fb-4c2bd19d66e6",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-08T11:32:09.979688+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.891081+00:00",
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
        "bytes": 360,
        "endpoint_path": "/argo/meta",
        "id": "aab8800f-fd7a-4cbf-884e-b057eac71cfa",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-08T11:32:09.979688+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.858215+00:00",
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
        "bytes": 975,
        "endpoint_path": "/argo",
        "id": "cbbbb0ab-f415-47e6-9857-622c85893914",
        "logical_request_sha256": "68175debe81fb3860b667fec6e3499a32cb34059bfcc87559da2ee674dff3aa2",
        "object_key": "raw/sha256/e1004098695855dec96be5c3833ecb1951fae0098618f3c18a55aa96caaa92b4.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.979411+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.827806+00:00",
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
        "id": "d004b825-5ffb-458f-b643-09dd23679cc0",
        "logical_request_sha256": "6aa435adb370fedc8032a70db4c6e581a73a039efdb96bd62cacbefad63e742f",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.979613+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.859184+00:00",
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
        "bytes": 871,
        "endpoint_path": "/argo",
        "id": "d142a1fa-5adb-4538-9d53-a152b8ec25b4",
        "logical_request_sha256": "c86e454265521caaef56fe1235b06dcd4c572c12fd70b7d31aeec8085f6f2353",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-08T11:32:09.978652+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-08T11:32:17.829958+00:00",
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
      "manifest_sha256": "d539955654fac1a7fa0ed012abd553baad03f07430a5777cb8576b0fe8cf27d4",
      "measurement_levels": 27,
      "profiles": 9
    },
    "full_stored": {
      "manifest_sha256": "d539955654fac1a7fa0ed012abd553baad03f07430a5777cb8576b0fe8cf27d4",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_snapshot": {
      "manifest_sha256": "d539955654fac1a7fa0ed012abd553baad03f07430a5777cb8576b0fe8cf27d4",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_stored": {
      "manifest_sha256": "d539955654fac1a7fa0ed012abd553baad03f07430a5777cb8576b0fe8cf27d4",
      "measurement_levels": 27,
      "profiles": 9
    }
  },
  "reference_time_utc": "2025-04-01 00:00:00+00:00",
  "run_eligible_balanced": true,
  "run_id": "70915a4a-e3fe-41e8-9d6b-a4d35b190cfe",
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
