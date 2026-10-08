"""Chunk CPU scale checks on a labelled synthetic chunk; no upstream, database or MinIO.

The benchmark runs only with STAGE1_BENCH=1 and writes reports/stage1-v4-bench-chunk.json.
The smoke test always runs with a tiny chunk.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    # stage1-v3 baseline was 65 s single-counted; this limit guards against regressions only.
    assert report["sum_measured_wall_s"] < 120


def test_chunk_profile_smoke(tmp_path):
    report = profile_chunk(2, 50, tmp_path)
    assert "stages" in report
    assert report["canonical_bytes_chunk"] > 0
    assert report["parquet_rows"] == 100
