"""Forecast evaluation (PRD section 30.4; ADR-0085): ``make eval-forecast``.

Runs the series policy, the baseline, the bounded SARIMA search, the rolling-origin backtest
and the selection over every committed snapshot in ``eval/forecast/series/`` and writes
``reports/eval_forecast_<date>.md`` with a JSON sidecar. No database is needed: the snapshots
carry the data-snapshot ids. ``--rebuild`` creates the forecast jobs through a running API
(``--api-url``), waits for them and saves their snapshots here first.

    python -m eval.forecast.harness [--grid full|small] [--folds 12] [--out reports/...]
    python -m eval.forecast.harness --rebuild --api-url http://127.0.0.1:8000
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from floatchat_core.forecast.model import ForecastLimits
from floatchat_core.forecast.runner import run_forecast
from floatchat_core.forecast.series import SeriesSnapshot

ROOT = Path(__file__).resolve().parents[2]
SERIES_DIR = Path(__file__).resolve().parent / "series"
CLIENT = "eval-forecast"
# The six series of PRD section 30.4 (three regions × two variables) plus a sparse region.
DEFINITIONS: list[dict[str, Any]] = [
    {
        "variable": variable,
        "geography": {"kind": "named_region", "value": region},
        "depth_dbar": {"min": 0, "max": 100},
        "horizon": 3,
    }
    for region in ("Arabian Sea", "Bay of Bengal", "Laccadive Sea", "Andaman Sea")
    for variable in ("temperature", "salinity")
]


def api(url: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"X-FloatChat-Client": CLIENT, "Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())  # type: ignore[no-any-return]


def rebuild(url: str) -> list[Path]:
    """Create the forecast jobs, wait, and save each run's snapshot (from the job's chunk)."""
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for definition in DEFINITIONS:
        created = api(url, "/v1/forecasts", definition)
        job_id = created["job"]["id"]
        print(
            f"{definition['geography']['value']} {definition['variable']}: job {job_id}", flush=True
        )
        while True:
            detail = api(url, f"/v1/jobs/{job_id}")
            if detail["job"]["state"] in ("completed", "partial", "cancelled", "failed"):
                break
            time.sleep(10)
        series_chunk = next((c for c in detail["chunks"] if c["kind"] == "series"), None)
        if (
            detail["job"]["state"] != "completed"
            or series_chunk is None
            or "snapshot" not in series_chunk["evidence"]
        ):
            print(f"  job ended {detail['job']['state']}: {detail['job'].get('error')}", flush=True)
            continue
        snapshot = series_chunk["evidence"]["snapshot"]
        name = f"{definition['geography']['value'].lower().replace(' ', '-')}-{definition['variable']}.json"
        path = SERIES_DIR / name
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        saved.append(path)
        print(
            f"  saved {path.relative_to(ROOT)} ({sum(1 for v in snapshot['values'] if v is not None)} months with values)",
            flush=True,
        )
    return saved


def evaluate(paths: list[Path], limits: ForecastLimits, horizon: int) -> list[dict[str, Any]]:
    results = []
    for path in sorted(paths):
        snapshot = SeriesSnapshot.from_dict(json.loads(path.read_text()))
        started = time.monotonic()
        outcome = run_forecast(snapshot, horizon, limits)
        results.append(
            {
                "file": str(path.relative_to(ROOT)),
                "snapshot_id": snapshot.id,
                "definition": snapshot.definition,
                "dataset_version": snapshot.dataset_version,
                "months_with_values": sum(1 for v in snapshot.values if v is not None),
                "seconds": round(time.monotonic() - started, 1),
                "outcome": outcome,
            }
        )
        print(f"{path.name}: {outcome['status']} in {results[-1]['seconds']} s", flush=True)
    return results


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def report(results: list[dict[str, Any]], limits: ForecastLimits, horizon: int, out: Path) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    versions = next((r["outcome"]["versions"] for r in results if r["outcome"].get("versions")), {})
    lines = [
        f"# Forecast evaluation ({date})",
        "",
        f"Commit `{commit}`; grid `{limits.grid}` ({len(results)} series); folds {limits.folds}; "
        f"horizons {list(limits.horizons)}; forecast horizon {horizon}; seed {limits.seed}; "
        f"statsmodels {versions.get('statsmodels')}, scipy {versions.get('scipy')}, numpy {versions.get('numpy')}. "
        "Protocol: rolling-origin, expanding window, refit per fold (PRD §30.4, ADR-0084). MASE is "
        "scaled by the in-sample MAE of the seasonal naive on each fold's training window; a "
        "candidate is selected only when its mean MASE beats the baseline by at least "
        f"{limits.improvement:.0%} and its residuals pass Ljung-Box at lag {limits.season}.",
        "",
        "## Series",
        "",
        "| Series | Snapshot | Dataset version | Months | Status | Selected | Baseline MASE (h1/h2/h3) | Selected MASE (h1/h2/h3) | Coverage 80/95 (selected) | Reason |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    wins = losses = refused = 0
    for item in results:
        outcome, definition = item["outcome"], item["definition"]
        label = f"{definition.get('region')} {definition.get('variable')}"
        dataset = item["dataset_version"]
        version = f"{str(dataset.get('latest_run', ''))[:8]}/{dataset.get('completed_runs', '')}"
        if outcome["status"] == "refused":
            refused += 1
            lines.append(
                f"| {label} | `{item['snapshot_id'][:8]}` | `{version}` | {item['months_with_values']} | refused | - | - | - | - | {outcome['reason']} |"
            )
            continue
        results_table = outcome["backtest"]["results"]
        baseline = results_table[outcome["backtest"]["baseline"]]
        selected = outcome["selection"]["selected"]
        chosen = selected["label"] if selected else "-"
        chosen_metrics = results_table.get(chosen) if selected else None
        b = "/".join(_fmt(baseline["horizons"][h].get("mase")) for h in ("1", "2", "3"))
        s = (
            "/".join(_fmt(chosen_metrics["horizons"][h].get("mase")) for h in ("1", "2", "3"))
            if chosen_metrics
            else "-"
        )
        cov = (
            f"{_fmt(sum(chosen_metrics['horizons'][h].get('coverage80', 0) for h in ('1', '2', '3')) / 3, 2)}/"
            f"{_fmt(sum(chosen_metrics['horizons'][h].get('coverage95', 0) for h in ('1', '2', '3')) / 3, 2)}"
            if chosen_metrics
            else "-"
        )
        if selected:
            wins += 1
        else:
            losses += 1
        reason = "; ".join(outcome["selection"]["reasons"][:2]) if not selected else ""
        lines.append(
            f"| {label} | `{item['snapshot_id'][:8]}` | `{version}` | {len(outcome['history']['months'])} | {outcome['status']} | {chosen} | {b} | {s} | {cov} | {reason} |"
        )
    lines += [
        "",
        f"Baseline beaten (model published): {wins}; baseline wins (experimental): {losses}; refused: {refused}.",
        "",
        "## Candidates per series (mean MASE over the horizons)",
        "",
        "| Series | Candidate | Mean MASE | MAE h1 | RMSE h1 | Coverage 80 h1 | Coverage 95 h1 | Misses |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        outcome = item["outcome"]
        if outcome["status"] == "refused":
            continue
        definition = item["definition"]
        label = f"{definition.get('region')} {definition.get('variable')}"
        for name, entry in outcome["backtest"]["results"].items():
            h1 = entry["horizons"]["1"]
            lines.append(
                f"| {label} | {name} | {_fmt(entry['mean_mase'])} | {_fmt(h1.get('mae'))} | {_fmt(h1.get('rmse'))} | "
                f"{_fmt(h1.get('coverage80'), 2)} | {_fmt(h1.get('coverage95'), 2)} | {sum(v.get('misses', 0) for v in entry['horizons'].values())} |"
            )
    lines += [
        "",
        "## Diagnostics and warnings",
        "",
    ]
    for item in results:
        outcome = item["outcome"]
        definition = item["definition"]
        label = f"{definition.get('region')} {definition.get('variable')}"
        if outcome["status"] == "refused":
            lines.append(f"- {label}: refused ({outcome['refusal_code']}).")
            continue
        diagnostics = outcome["selection"]["diagnostics"]
        lines.append(
            f"- {label}: {outcome['status']}; Ljung-Box p {_fmt(diagnostics.get('ljung_box_p'))}; "
            f"residual mean {_fmt(diagnostics.get('residual_mean'), 4)}; "
            + ("; ".join(outcome["warnings"]) if outcome["warnings"] else "no warnings")
        )
    lines += [
        "",
        "Interpretation boundary (PRD §12.4): every run carries the text that it is a statistical "
        "extrapolation of a derived observational series, not a physics-based ocean forecast.",
    ]
    out.write_text("\n".join(lines) + "\n")
    out.with_suffix(".json").write_text(
        json.dumps(
            {
                "commit": commit,
                "limits": limits.model_dump(),
                "horizon": horizon,
                "results": results,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )
    print(str(out.relative_to(ROOT)))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--grid", choices=("full", "small"), default="full")
    parser.add_argument("--folds", type=int, default=12)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument(
        "--series", default=None, help="only snapshot files whose name contains this"
    )
    parser.add_argument("--out", default=None)
    arguments = parser.parse_args(argv)
    if arguments.rebuild:
        rebuild(arguments.api_url)
    paths = sorted(SERIES_DIR.glob("*.json"))
    if arguments.series:
        paths = [p for p in paths if arguments.series in p.name]
    if not paths:
        print(
            "no snapshots under eval/forecast/series; run with --rebuild against a stack",
            file=sys.stderr,
        )
        return 2
    limits = ForecastLimits(grid=arguments.grid, folds=arguments.folds)
    results = evaluate(paths, limits, arguments.horizon)
    out = (
        Path(arguments.out)
        if arguments.out
        else ROOT / "reports" / f"eval_forecast_{datetime.now(UTC):%Y-%m-%d}.md"
    )
    report(results, limits, arguments.horizon, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
