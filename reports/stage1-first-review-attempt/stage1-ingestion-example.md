# Stage 1 persisted run report

Run: `1289e2fb-558c-4357-b860-852c3914e5a8`. State: **partial**.

Reference UTC: `2025-04-01 00:00:00+00:00`. Frozen: True.

Scientific no change: False; active partitions no change: False.

Full/eligible reconciliation: True / True.

Coverage proved complete: False; gaps: 178.

Counts distinguish payload attempts, profile occurrences and measurement levels.
DataFrame deep memory includes its index and is distinct from peak RSS.

Complete persisted evidence (including timings, reasons, availability, versions, raw references and measured storage comparisons):

```json
{
  "acceptance_status": "not_certified_by_this_report",
  "active_generation_ids": [
    "87ee82bf-0d75-417e-a293-26284d95adec"
  ],
  "active_partition_no_change": false,
  "after_at_report_snapshot": {
    "active_generation_sha256": "77dd9b7783b7e29482e3efc3d49bde95ce70567028d997de6f2e8db3f4945c21",
    "active_partitions": 1,
    "attempts": 46,
    "audit_rows": 143,
    "floats": 1,
    "measurement_levels": 27,
    "profile_manifest_sha256": "b9d5ee141e82de7e3c0ea3f9439a8c2041e48a89a86701a1bfaf343ebb1669b8",
    "profiles": 9,
    "runs": 9
  },
  "audit_and_attempt_rows_may_increase": true,
  "before": {
    "active_generation_sha256": "0896ef8b1a593cf762d2c0d1aa5b5d7dd0f89884070b1af61fcfa76f9c262c02",
    "active_partitions": 1,
    "attempts": 38,
    "audit_rows": 123,
    "floats": 1,
    "measurement_levels": 24,
    "profile_manifest_sha256": "98e39efb06d38282eb7a941901fe6c49865bfeb0c42346a73700c77d12aac62e",
    "profiles": 8,
    "reconciliation": {
      "full_snapshot": {
        "manifest_sha256": "98e39efb06d38282eb7a941901fe6c49865bfeb0c42346a73700c77d12aac62e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "full_stored": {
        "manifest_sha256": "98e39efb06d38282eb7a941901fe6c49865bfeb0c42346a73700c77d12aac62e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_snapshot": {
        "manifest_sha256": "98e39efb06d38282eb7a941901fe6c49865bfeb0c42346a73700c77d12aac62e",
        "measurement_levels": 24,
        "profiles": 8
      },
      "run_eligible_stored": {
        "manifest_sha256": "98e39efb06d38282eb7a941901fe6c49865bfeb0c42346a73700c77d12aac62e",
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
          "inventory_after": "7d24e90b-9a33-4c4a-a013-eafa4c03b9e1",
          "inventory_before": "9d534209-d9ab-4903-be0e-af56dfc76fce",
          "metadata": "4bd60323-34b8-4c7e-ab8f-05261f33d07f",
          "profile": "0607e148-138e-4f78-96c0-0bee4e16ecec"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": null,
      "control_epoch": 2,
      "fence": 2,
      "id": "b3760988-6732-45fb-88f3-011caefbf9c0",
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
          "inventory_after": "f2da858f-ba6a-455b-a320-b994dc60003d",
          "inventory_before": "b3acf639-0f67-4c68-9463-49e4109cbe08",
          "metadata": "8522db18-dcf6-4d65-b410-07ac56aa932c",
          "profile": "3889a3f9-4fdd-47eb-94d0-c059e19459b0"
        },
        "unknown_level_profiles": 0
      },
      "completed_at": "2026-10-06 18:32:42.950274+00:00",
      "control_epoch": 2,
      "fence": 1,
      "id": "b6100e52-a1f7-494a-8dd0-0cb6d94da98f",
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
  "contract": "stage1-v2",
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
      "87ee82bf-0d75-417e-a293-26284d95adec"
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
        "bytes": 20175,
        "committed_at": "2026-10-06T18:32:42.947419+00:00",
        "generation": 9,
        "id": "87ee82bf-0d75-417e-a293-26284d95adec",
        "levels": 27,
        "logical_key": "argovis/core/2025-01/70:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "object_key": "normalised/sha256/6380c80bbbe5b8d605f2f13a924492336c2f5c0e1613956eb1e3482c688ef68b.parquet",
        "profiles": 9,
        "sha256": "6380c80bbbe5b8d605f2f13a924492336c2f5c0e1613956eb1e3482c688ef68b",
        "verification_evidence": {
          "membership_sha256": "ee7a46e997b4e602f51c5601c3f82205caab47e3a1e9c97c603fc4f8d47f4f57",
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
            "pandas_to_parquet_ratio": 2.9295167286245354,
            "pandas_version": "2.3.3",
            "parquet_bytes": 20175,
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
        "verified_at": "2026-10-06T18:32:42.694626+00:00",
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
        "http_status": null,
        "origin": "captured"
      }
    ],
    "attempt_timing": [
      {
        "attempts": 8,
        "disposition": "verified_raw",
        "elapsed_seconds_max": 0.030842,
        "elapsed_seconds_sum": 0.211521,
        "first_started_at": "2026-10-06T18:32:42.323725+00:00",
        "last_finished_at": "2026-10-06T18:32:42.456854+00:00",
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
        "committed_at": "2026-10-06T18:29:56.714901+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "2fd970c3-eaf9-4746-9d10-fd5f486f92c9",
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
        "committed_at": "2026-10-06T18:32:33.037005+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "40170bd5-b7f9-4af5-a069-8bcce1ba2db1",
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
        "committed_at": "2026-10-06T18:30:59.737449+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "81c928dd-bfc8-4b98-9169-1cba98643429",
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
        "committed_at": "2026-10-06T18:32:12.502493+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "8f601481-258a-4bf8-b33f-4f34df73b695",
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
        "committed_at": "2026-10-06T18:30:29.467063+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "8f92c470-8daa-4e4d-9dbf-83f685efb419",
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
        "committed_at": "2026-10-06T18:31:52.225879+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "c7faf488-6bd9-4594-b564-a846392d11d3",
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
        "committed_at": "2026-10-06T18:31:30.216641+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "dc069c31-7abb-4fe8-a366-185e9618d617",
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
        "committed_at": "2026-10-06T18:32:42.949006+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "e924661d-9a1c-4e66-94d6-9912d59aefaa",
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
        "committed_at": "2026-10-06T18:29:25.891519+00:00",
        "fetch_disposition": "profiles_returned",
        "id": "ff3fb6da-0bdd-4592-9227-6c014af480d3",
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
      "execution_seconds": 90
    },
    "phase_timings": [
      {
        "episodes": 1,
        "phase": "complete",
        "wall_seconds_sum": 29.554567
      },
      {
        "episodes": 1,
        "phase": "failed",
        "wall_seconds_sum": 0.003073
      },
      {
        "episodes": 2,
        "phase": "fetching",
        "wall_seconds_sum": 0.25842
      },
      {
        "episodes": 2,
        "phase": "landed",
        "wall_seconds_sum": 0.007871
      },
      {
        "episodes": 2,
        "phase": "planned",
        "wall_seconds_sum": 0.12399
      },
      {
        "episodes": 2,
        "phase": "publishing",
        "wall_seconds_sum": 30.469713
      },
      {
        "episodes": 2,
        "phase": "validating",
        "wall_seconds_sum": 0.066918
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
      "canonical_bytes": 394048,
      "controller_claims": 2,
      "http_attempts": 0,
      "received_bytes": 0
    },
    "run_timing": {
      "created_actual_utc": "2026-10-06T18:32:34.084021+00:00",
      "elapsed_seconds": 38.420896,
      "terminal_event_actual_utc": "2026-10-06T18:33:12.504917+00:00"
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
        "bytes": 975,
        "endpoint_path": "/argo",
        "id": "0607e148-138e-4f78-96c0-0bee4e16ecec",
        "logical_request_sha256": "68175debe81fb3860b667fec6e3499a32cb34059bfcc87559da2ee674dff3aa2",
        "object_key": "raw/sha256/e1004098695855dec96be5c3833ecb1951fae0098618f3c18a55aa96caaa92b4.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.082195+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.397740+00:00",
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
        "bytes": 975,
        "endpoint_path": "/argo",
        "id": "3889a3f9-4fdd-47eb-94d0-c059e19459b0",
        "logical_request_sha256": "f6f66b2fb3bb5217d19bd77717ed29ac8a6bc05571a81d29fbc795b7f3f142ba",
        "object_key": "raw/sha256/0a55d70bc1beac31d5d561305cee614ca004f0a26405adac970241b7317ee39c.json",
        "origin": "captured",
        "request_parameters": {
          "data": "all",
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.081272+00:00",
        "role": "profile",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.384000+00:00",
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
        "id": "4bd60323-34b8-4c7e-ab8f-05261f33d07f",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-06T18:32:34.082471+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.454796+00:00",
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
        "id": "7d24e90b-9a33-4c4a-a013-eafa4c03b9e1",
        "logical_request_sha256": "6aa435adb370fedc8032a70db4c6e581a73a039efdb96bd62cacbefad63e742f",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.082354+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.426545+00:00",
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
        "id": "8522db18-dcf6-4d65-b410-07ac56aa932c",
        "logical_request_sha256": "46775e61266b0b2bda8d85d07c9f34c2430b92e2fc2ddbb4ad6dc52ec64bfd9e",
        "object_key": "raw/sha256/8c707f40b8f74c5d9aa03d743b2ae523b2c92af51d08decdb4c229c605e1ea29.json",
        "origin": "captured",
        "request_parameters": {
          "id": "1901094_m0"
        },
        "retrieved_at": "2026-10-06T18:32:34.082471+00:00",
        "role": "metadata",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.442181+00:00",
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
        "id": "9d534209-d9ab-4903-be0e-af56dfc76fce",
        "logical_request_sha256": "7830f50cf0f7d2638d4742f9fd54659dd056448b2e753c8b7fb29ea2229fc293",
        "object_key": "raw/sha256/15f15a2fa4e7bef3fc5188de13724c92f38f9350f148f3da51ddf50e89703034.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[79.999999,9.999999],[90.000001,9.999999],[90.000001,20.000001],[79.999999,20.000001],[79.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.081805+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.365745+00:00",
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
        "id": "b3acf639-0f67-4c68-9463-49e4109cbe08",
        "logical_request_sha256": "6729ab7a2212e7692bf4d9f48474ced9123bb7741191b8263b6cb2e212b64dcc",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.080969+00:00",
        "role": "inventory_before",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.352218+00:00",
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
        "id": "f2da858f-ba6a-455b-a320-b994dc60003d",
        "logical_request_sha256": "c86e454265521caaef56fe1235b06dcd4c572c12fd70b7d31aeec8085f6f2353",
        "object_key": "raw/sha256/5a422cef487f721955021375d63ada500635132c34adee552823daaf211bdc48.json",
        "origin": "captured",
        "request_parameters": {
          "endDate": "2025-01-07T00:00:00Z",
          "polygon": "[[69.999999,9.999999],[80.000001,9.999999],[80.000001,20.000001],[69.999999,20.000001],[69.999999,9.999999]]",
          "startDate": "2025-01-01T00:00:00Z"
        },
        "retrieved_at": "2026-10-06T18:32:34.081576+00:00",
        "role": "inventory_after",
        "sanitization": {
          "credential_fields_removed": 0,
          "input_kind": "synthetic_offline_chunk_fixture",
          "input_origin": "captured",
          "read_at_actual_utc": "2026-10-06T18:32:42.414175+00:00",
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
      "manifest_sha256": "b9d5ee141e82de7e3c0ea3f9439a8c2041e48a89a86701a1bfaf343ebb1669b8",
      "measurement_levels": 27,
      "profiles": 9
    },
    "full_stored": {
      "manifest_sha256": "b9d5ee141e82de7e3c0ea3f9439a8c2041e48a89a86701a1bfaf343ebb1669b8",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_snapshot": {
      "manifest_sha256": "b9d5ee141e82de7e3c0ea3f9439a8c2041e48a89a86701a1bfaf343ebb1669b8",
      "measurement_levels": 27,
      "profiles": 9
    },
    "run_eligible_stored": {
      "manifest_sha256": "b9d5ee141e82de7e3c0ea3f9439a8c2041e48a89a86701a1bfaf343ebb1669b8",
      "measurement_levels": 27,
      "profiles": 9
    }
  },
  "reference_time_utc": "2025-04-01 00:00:00+00:00",
  "run_eligible_balanced": true,
  "run_id": "1289e2fb-558c-4357-b860-852c3914e5a8",
  "scientific_level_delta_balanced": true,
  "scientific_no_change": false,
  "snapshot_evidence_scope": "Committed membership and persisted Parquet verification; this report does not replace a fresh byte-integrity selector check.",
  "state": "partial",
  "terminal_leaves": 2,
  "termination_reason": "deadline_expired"
}
```
