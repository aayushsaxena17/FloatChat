"""Census-weighted run model from the offline per-level measurements.

Inputs are committed reports; outputs are projections for Jan-Mar 2025 only and
are labelled as such. HTTP figures come from the live transport episode report.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--db",
        type=Path,
        action="append",
        default=None,
        help="DB probe report(s) to use instead of the stage1-v3 probes",
    )
    parser.add_argument(
        "--cpu",
        type=Path,
        default=ROOT / "reports/stage1-perf-chunk-cpu-87x699.json",
        help="chunk CPU profile JSON (relative paths are resolved from the cwd)",
    )
    args = parser.parse_args()
    census = json.loads((ROOT / "reports/stage1-inventory-census.json").read_text())
    cpu = json.loads(args.cpu.read_text())
    cpu_path = args.cpu.resolve()
    cpu_label = (
        cpu_path.relative_to(ROOT).as_posix() if cpu_path.is_relative_to(ROOT) else str(cpu_path)
    )
    db_paths = args.db or [
        ROOT / "reports/stage1-perf-db-probe.json",
        ROOT / "reports/stage1-perf-db-probe-87-alone.json",
    ]
    db_reports = [json.loads(Path(path).read_text()) for path in db_paths]
    transport = json.loads((ROOT / "reports/stage1-live-transport-8e8da1d4.json").read_text())
    slots = census["slot_profiles"]
    depth = {"2025-01": 699, "2025-02": 384, "2025-03": 384}  # ADR-0041 / depth spot-check
    levels = sum(count * depth[key[:7]] for key, count in slots.items())
    nonempty = sum(1 for count in slots.values() if count)
    empty = 270 - nonempty
    stages = cpu["stages"]
    per_level = {}
    chunk_levels = cpu["profiles"] * cpu["levels_per_profile"]
    # One table for both pipelines: the v3 stage names and the v4 names. A name the report
    # does not carry counts as 0 s with multiplicity 1 and is listed in stage_names_missing.
    multiplicity = {
        "sanitize_raw(profile payload)": 1,
        "validate_raw(profile payload) x1": 3,
        "documents() decode profile payload x1": 5,
        "map_profile + budget.encode (all profiles)": 1,
        "spool.add (all)": 1,
        "spool.prepare (restore+certify, no DB)": 1,
        "spool.membership(slot)": 1,
        "spool.profiles(slot) re-read (receipts pass)": 1,  # v3 only
        "write_snapshot (write+verify+storage_comparison)": 1,
        "publish_verified (certificate full verify + 2 light verifies; memory store)": 1,
        "spool.write_candidates (NDJSON for COPY)": 1,  # v3 only
        "spool.candidates (slim JSON)": 1,  # v4 only
        "spool.level_tables (Arrow)": 1,  # v4 only
    }
    # A v4 report records the counts it read from the code (validate_raw is 1, not 3:
    # publish_verified validates once). They override the v3 defaults above.
    recorded = cpu.get("stage_multiplicity")
    if recorded:
        multiplicity.update(recorded)
    missing = [name for name in multiplicity if name not in stages]
    # Raw-side stages scale with every source column, not just core. The census
    # population averages ~34 KB raw per profile (200 MB / 5,845); the 6-column
    # synthetic basis is ~21 KB at 699 levels, the 24-column basis ~88 KB, so the
    # raw-side stages are scaled by 34/21 = 1.6 (see stage1-perf-chunk-cpu-22x699-bgc24.json).
    raw_side = {
        "sanitize_raw(profile payload)",
        "validate_raw(profile payload) x1",
        "documents() decode profile payload x1",
    }
    raw_factor = round(34_000 / (cpu["raw_profile_payload_bytes"] / cpu["profiles"]), 2)
    cpu_per_level_us = 0.0
    for name, times in multiplicity.items():
        factor = raw_factor if name in raw_side else 1.0
        seconds = stages[name]["wall_s"] if name in stages else 0.0
        value = seconds * times * factor / chunk_levels * 1e6
        per_level[name] = {
            "multiplicity": times,
            "raw_column_factor": factor,
            "us_per_level": round(value, 1),
        }
        cpu_per_level_us += value
    # DB: linear fit through the three probe points (COPY + commit), per level. The v4 probe
    # names its staging stage "stage_candidates + stage_levels COPY" (v3: "stage_file ...").
    copy_names = ("stage_candidates + stage_levels COPY", "stage_file COPY to ingestion_staging")

    def copy_seconds(scenario):
        stages_s = scenario["stages_s"]
        return stages_s[next(name for name in copy_names if name in stages_s)]

    scenarios = [
        (scenario, Path(str(path)).stem)
        for path, report in zip(db_paths, db_reports, strict=True)
        for scenario in report["scenarios"]
    ]
    points = [
        (s["levels"], copy_seconds(s) + s["stages_s"]["commit_publication"]) for s, _ in scenarios
    ]
    db_us_per_level = {
        f"{s['levels']} levels ({tag}, {s['profiles']}x{s['levels_per_profile']})": round(
            (copy_seconds(s) + s["stages_s"]["commit_publication"]) / s["levels"] * 1e6, 1
        )
        for s, tag in scenarios
    }
    db_mid = sum(sec for _, sec in points) / sum(lv for lv, _ in points) * 1e6
    attempts = transport["attempts"]

    def mean(role, status):
        values = [
            a["seconds"] for a in attempts if a["role"] == role and a["http_status"] == status
        ]
        return sum(values) / len(values) if values else None

    http = {
        "inventory_before_200_s": mean("inventory_before", 200),
        "profile_200_s": mean("profile", 200),
        "inventory_after_200_s": mean("inventory_after", 200),
        "inventory_before_404_s": mean("inventory_before", 404),
        "profile_404_s": mean("profile", 404),
        "inventory_after_404_s": mean("inventory_after", 404),
        "metadata_200_s": mean("metadata", 200),
    }
    # Upstream latency is episodic (ADR-0045: 1.2-1.6 s uncached month inventories
    # after an episode, 25-80 s during one). Bracket it: "slow" = measured means of
    # the 8e8da1d4 episode run; "fast" = 5 s inventory, 10 s data=all, 1.5 s after.
    selection_slow = sum(
        http[k] for k in ("inventory_before_200_s", "profile_200_s", "inventory_after_200_s")
    )
    selection_fast = 5.0 + 10.0 + 1.5
    selection_empty = sum(
        http[k] for k in ("inventory_before_404_s", "profile_404_s", "inventory_after_404_s")
    )
    metadata_requests = 2000  # brief section 3; one /argo/meta per float per chunk
    worker_cpu_h = levels * cpu_per_level_us / 1e6 / 3600
    db_h = levels * db_mid / 1e6 / 3600
    metadata_h = metadata_requests * http["metadata_200_s"] / 3600
    projection = {
        "levels_jan_mar": levels,
        "nonempty_chunks": nonempty,
        "empty_chunks": empty,
        "worker_cpu_hours": round(worker_cpu_h, 2),
        "db_copy_commit_hours": round(db_h, 2),
        "http_selection_hours_fast": round(
            (nonempty * selection_fast + empty * selection_empty) / 3600, 2
        ),
        "http_selection_hours_slow": round(
            (nonempty * selection_slow + empty * selection_empty) / 3600, 2
        ),
        "http_metadata_hours": round(metadata_h, 2),
    }
    projection["serial_total_hours_fast"] = round(
        worker_cpu_h + db_h + projection["http_selection_hours_fast"] + metadata_h, 2
    )
    projection["serial_total_hours_slow"] = round(
        worker_cpu_h + db_h + projection["http_selection_hours_slow"] + metadata_h, 2
    )
    projection["captured_replay_hours_no_http"] = round(worker_cpu_h + db_h, 2)
    # Cross-check: live session 7153be6379df84de completed its first 70 chunks (controller
    # order: January, 19 empty, 51 non-empty, 1,502 profiles) in 66 minutes.
    first = {
        "chunks": 70,
        "empty": 19,
        "nonempty": 51,
        "profiles": 1502,
        "measured_seconds": 66 * 60,
    }
    first_levels = first["profiles"] * 699
    first["model_seconds_fast"] = round(
        first_levels * (cpu_per_level_us + db_mid) / 1e6
        + first["nonempty"] * selection_fast
        + first["empty"] * selection_empty
        + first["profiles"] * metadata_requests / 5845 * http["metadata_200_s"]
    )
    first["model_seconds_slow"] = round(
        first_levels * (cpu_per_level_us + db_mid) / 1e6
        + first["nonempty"] * selection_slow
        + first["empty"] * selection_empty
        + first["profiles"] * metadata_requests / 5845 * http["metadata_200_s"]
    )
    projection["live_first_70_chunks_cross_check"] = first
    report = {
        "kind": "stage1_perf_run_model",
        "scope": "Projection for Jan-Mar 2025 from the census and offline measurements; "
        "not a measurement of a live run",
        "inputs": {
            "census": "reports/stage1-inventory-census.json",
            "cpu": cpu_label,
            "cpu_pipeline": "stage1-v4" if recorded else "stage1-v3",
            "db_pipeline": (
                "stage1-v4"
                if all(copy_names[0] in s["stages_s"] for s, _ in scenarios)
                else "stage1-v3 (probe ran before publication v4)"
            ),
            "db": [str(path) for path in db_paths],
            "transport": "reports/stage1-live-transport-8e8da1d4.json",
            "depth_levels_per_profile_by_month": depth,
            "metadata_requests_assumed": metadata_requests,
            "raw_column_factor": raw_factor,
            "raw_calibration": "reports/stage1-perf-chunk-cpu-22x699-bgc24.json",
        },
        "cpu_us_per_level_by_stage": per_level,
        "stage_names_missing": missing,
        "cpu_us_per_level_total": round(cpu_per_level_us, 1),
        "db_us_per_level_copy_plus_commit": db_us_per_level,
        "db_us_per_level_pooled": round(db_mid, 1),
        "http_mean_seconds_by_role": http,
        "projection": projection,
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                in (
                    "stage_names_missing",
                    "cpu_us_per_level_total",
                    "db_us_per_level_copy_plus_commit",
                    "db_us_per_level_pooled",
                    "http_mean_seconds_by_role",
                    "projection",
                )
            },
            indent=1,
        )
    )
    for k, v in per_level.items():
        print(f"{v['us_per_level']:8.1f} us/level x{v['multiplicity']}  {k}")


if __name__ == "__main__":
    main()
