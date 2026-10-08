"""Chunk CPU scale checks on a labelled synthetic chunk; no upstream, database or MinIO.

The benchmark runs only with STAGE1_BENCH=1 and writes reports/stage1-v4-bench-chunk.json
(the stage1-v3 numbers it is compared with are kept in
reports/stage1-v3-bench-chunk-baseline.json). The smoke tests always run with a tiny chunk.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from floatchat_core.ingestion import parquet

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from stage1_perf_profile import print_table, profile_chunk  # noqa: E402

REPORT = ROOT / "reports/stage1-v4-bench-chunk.json"


@pytest.mark.skipif(os.environ.get("STAGE1_BENCH") != "1", reason="set STAGE1_BENCH=1")
def test_chunk_cpu_budget_87x699(tmp_path):
    report = profile_chunk(87, 699, tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    report["git_head"] = head.stdout.strip()
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print_table(report)
    # The stage1-v3 single-counted baseline was 58.2 s; v4 must not regress above it.
    assert report["sum_measured_wall_s"] < 60


@pytest.fixture
def verify_calls(monkeypatch):
    """Count the row-by-row verify_snapshot calls write_snapshot makes."""
    calls = []
    original = parquet.verify_snapshot

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(parquet, "verify_snapshot", spy)
    return calls


def test_chunk_profile_smoke(tmp_path, verify_calls):
    report = profile_chunk(2, 50, tmp_path)
    assert "stages" in report
    assert report["canonical_bytes_chunk"] > 0
    assert report["parquet_rows"] == 100
    # The v4 path: slim candidate JSON and Arrow level tables replace the NDJSON staging file.
    assert report["staging_json_bytes"] > 0
    assert report["staging_level_rows"] == 100
    assert "spool.candidates (slim JSON)" in report["stages"]
    assert "spool.level_tables (Arrow)" in report["stages"]
    assert "spool.write_candidates (NDJSON for COPY)" not in report["stages"]
    # The default path does not re-decode the written file row by row.
    assert verify_calls == []
    assert report["audit"] is False
    assert set(report["stage_multiplicity"]) <= set(report["stages"])


def test_chunk_profile_smoke_audit(tmp_path, verify_calls):
    report = profile_chunk(2, 50, tmp_path, audit=True)
    assert report["audit"] is True
    assert report["parquet_rows"] == 100
    assert len(verify_calls) == 1


def test_run_model_accepts_the_v4_report(tmp_path):
    for needed in (
        "stage1-inventory-census.json",
        "stage1-live-transport-8e8da1d4.json",
        "stage1-perf-db-probe.json",
        "stage1-perf-db-probe-87-alone.json",
    ):
        if not (ROOT / "reports" / needed).exists():
            pytest.skip(f"reports/{needed} is not in this checkout")
    cpu = tmp_path / "cpu.json"
    cpu.write_text(json.dumps(profile_chunk(2, 50, tmp_path / "work")))
    output = tmp_path / "model.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/stage1_perf_model.py"),
            "--output",
            str(output),
            "--cpu",
            str(cpu),
        ],
        check=True,
        capture_output=True,
    )
    model = json.loads(output.read_text())
    assert model["inputs"]["cpu_pipeline"] == "stage1-v4"
    assert model["stage_names_missing"] == [
        "spool.profiles(slot) re-read (receipts pass)",
        "spool.write_candidates (NDJSON for COPY)",
    ]
    by_stage = model["cpu_us_per_level_by_stage"]
    assert by_stage["validate_raw(profile payload) x1"]["multiplicity"] == 1
    assert by_stage["spool.candidates (slim JSON)"]["multiplicity"] == 1
    assert by_stage["spool.write_candidates (NDJSON for COPY)"]["us_per_level"] == 0
    assert model["cpu_us_per_level_total"] > 0
