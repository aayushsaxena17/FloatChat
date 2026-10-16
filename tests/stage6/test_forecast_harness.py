"""The forecast harness over a committed-style snapshot writes a report with the required header."""

import json
import sys
from pathlib import Path

import numpy as np
from floatchat_core.forecast.model import ForecastLimits

from eval.forecast import harness


def synthetic_snapshot(path: Path, n: int = 72, seed: int = 3) -> None:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    values = 28 + 0.01 * t + 2.0 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 0.15, n)
    document = {
        "schema": "series-snapshot-v1",
        "id": "11111111-1111-5111-8111-111111111111",
        "definition": {"variable": "temperature", "region": "Test Sea", "min_profiles": 5},
        "dataset_version": {"id": "env", "latest_run": "run-1", "completed_runs": 3},
        "months": [f"{2019 + i // 12}-{i % 12 + 1:02d}" for i in range(n)],
        "values": [float(v) for v in values],
        "counts": [10] * n,
        "partitions": [{"id": "p1", "sha256": "a" * 64}],
        "versions": {},
        "built_at": "2026-10-16T00:00:00Z",
        "application_commit": "test",
    }
    path.write_text(json.dumps(document))


def test_harness_writes_a_report_and_sidecar_from_snapshots(tmp_path: Path, monkeypatch) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    synthetic_snapshot(series_dir / "test-sea-temperature.json")
    short = json.loads((series_dir / "test-sea-temperature.json").read_text())
    short["months"], short["values"], short["counts"] = (
        short["months"][:12],
        short["values"][:12],
        short["counts"][:12],
    )
    short["definition"]["region"] = "Short Sea"
    (series_dir / "short-sea-temperature.json").write_text(json.dumps(short))
    monkeypatch.setattr(harness, "SERIES_DIR", series_dir)
    out = tmp_path / "eval_forecast_test.md"
    code = harness.main(["--grid", "small", "--folds", "6", "--out", str(out)])
    assert code == 0
    text = out.read_text()
    assert text.startswith("# Forecast evaluation (")
    assert "grid `small`" in text and "folds 6" in text and "seed 20261016" in text
    assert "| Test Sea temperature |" in text and "| Short Sea temperature |" in text
    assert "refused" in text and "history_too_short" in text
    assert "Interpretation boundary" in text
    sidecar = json.loads(out.with_suffix(".json").read_text())
    assert sidecar["limits"]["grid"] == "small" and len(sidecar["results"]) == 2
    statuses = {r["definition"]["region"]: r["outcome"]["status"] for r in sidecar["results"]}
    assert statuses["Short Sea"] == "refused" and statuses["Test Sea"] in (
        "published",
        "experimental",
    )
    assert sidecar["results"][0]["dataset_version"]["latest_run"] == "run-1"
    assert ForecastLimits(grid="small").grid == "small"
    assert sys.version_info >= (3, 12)
