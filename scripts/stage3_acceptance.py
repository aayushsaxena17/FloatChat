"""Stage 3 acceptance on the imported Stage 1 dataset (ADR-0063; plan W9).

    uv run --all-packages --frozen python scripts/stage3_acceptance.py \
        --base-url http://127.0.0.1:5173 --api-url http://127.0.0.1:8000

Runs the Playwright suite against a running stack, asks the suite to save screenshots at its
checkpoints (``STAGE3_SHOTS_DIR``), reads the dataset identity and the scenario counts from the
API, and writes ``reports/stage3-acceptance-<date>.json`` beside the PNG directory. Every number
in the report comes from the API or from the Playwright JSON reporter; nothing is typed by hand.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = {
    "region": "Arabian Sea",
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-02-01T00:00:00Z",
    "depth_min": "0",
    "depth_max": "100",
}


def get(base: str, path: str, params: dict[str, str] | None = None) -> dict:
    url = base + path + (f"?{urllib.parse.urlencode(params)}" if params else "")
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def count_profiles(api: str) -> int:
    total, cursor = 0, None
    while True:
        params = {**SCENARIO, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        page = get(api, "/v1/profiles", params)
        total += int(page["result"]["row_count"])
        cursor = page["next_cursor"]
        if not cursor:
            return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    arguments = parser.parse_args()
    shots = ROOT / "reports" / f"stage3-acceptance-{arguments.date}"
    shots.mkdir(parents=True, exist_ok=True)
    report_path = ROOT / "reports" / f"stage3-acceptance-{arguments.date}.json"
    results_path = shots / "playwright.json"
    coverage = get(
        arguments.api_url,
        "/v1/catalog/coverage",
        {k: v for k, v in SCENARIO.items() if k != "depth_min" and k != "depth_max"},
    )
    started = time.monotonic()
    environment = dict(
        os.environ,
        BASE_URL=arguments.base_url,
        STAGE3_SHOTS_DIR=str(shots),
        PLAYWRIGHT_JSON_OUTPUT_NAME=str(results_path),
    )
    run = subprocess.run(
        ["pnpm", "--filter", "@floatchat/web", "exec", "playwright", "test", "--reporter=json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 1)
    results = json.loads(results_path.read_text()) if results_path.exists() else None
    specs = []
    if results:
        for suite in results.get("suites", []):
            for inner in [suite, *suite.get("suites", [])]:
                for spec in inner.get("specs", []):
                    specs.append(
                        {
                            "title": spec["title"],
                            "ok": spec["ok"],
                            "duration_ms": sum(t["results"][0]["duration"] for t in spec["tests"]),
                        }
                    )
    report = {
        "stage": 3,
        "date": arguments.date,
        "base_url": arguments.base_url,
        "api_url": arguments.api_url,
        "environment": coverage["environment"],
        "scenario": {
            **SCENARIO,
            "profiles": count_profiles(arguments.api_url),
            "coverage": {
                key: coverage["coverage"][key]
                for key in (
                    "slots_total",
                    "slots_covered",
                    "slots_empty_verified",
                    "slots_missing",
                    "estimated_profiles",
                    "estimated_levels",
                    "partial",
                )
            },
        },
        "playwright": {
            "exit_code": run.returncode,
            "elapsed_seconds": elapsed,
            "specs": specs,
            "stderr_tail": run.stderr[-2000:],
        },
        "screenshots": sorted(path.name for path in shots.glob("*.png")),
        "passed": run.returncode == 0 and bool(specs) and all(spec["ok"] for spec in specs),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("passed", "scenario", "screenshots")}, indent=2))
    print(f"report: {report_path.relative_to(ROOT)}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
