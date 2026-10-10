"""Record API responses from the running dev stack for the web unit tests (plan section 6).

    uv run --all-packages --frozen python scripts/capture_web_fixtures.py --base-url http://127.0.0.1:8000

Identifiers, digests and timestamps are kept as served: the fixtures are recordings, not
inventions. Each file is the exact JSON body of one request; the request is recorded in
``apps/web/src/test/fixtures/index.json``.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "apps/web/src/test/fixtures"
RANGE = {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"}
REGION = "Arabian Sea"


def fetch(base: str, method: str, path: str, params: dict[str, str] | None = None, body=None):
    url = base + path + (f"?{urllib.parse.urlencode(params)}" if params else "")
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    base = parser.parse_args().base_url
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    def record(name: str, method: str, path: str, params=None, body=None, trim=None):
        document = fetch(base, method, path, params, body)
        if trim is not None:
            document = trim(document)
        (OUTPUT / f"{name}.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        index[name] = {"method": method, "path": path, "params": params, "body": body}
        return document

    record("parameters", "GET", "/v1/catalog/parameters")
    record("coverage", "GET", "/v1/catalog/coverage", {"region": REGION, **RANGE})
    profiles = record(
        "profiles",
        "GET",
        "/v1/profiles",
        {"region": REGION, "depth_min": "0", "depth_max": "100", "limit": "25", **RANGE},
    )
    first = profiles["result"]["rows"][0]
    names = [c["name"] for c in profiles["result"]["columns"]]
    profile_id = first[names.index("id")]
    platform = first[names.index("platform_number")]
    record("profile", "GET", f"/v1/profiles/{profile_id}", {"depth_max": "100"})
    record("float", "GET", f"/v1/floats/{platform}", {**RANGE, "limit": "50"})
    plan = {
        "time_range": RANGE,
        "geography": {"kind": "named_region", "value": REGION},
        "depth_dbar": {"min": 0, "max": 100},
        "variables": ["temperature", "salinity"],
        "qc_policy": "science_ready",
        "operation": {
            "kind": "aggregate",
            "group_by": ["day"],
            "metrics": ["mean", "count"],
            "unit": "profile",
        },
        "presentation": {"kind": "line_chart"},
    }
    record("query-line", "POST", "/v1/query", body=plan)
    record(
        "query-histogram",
        "POST",
        "/v1/query",
        body={
            **plan,
            "variables": ["temperature"],
            "operation": {
                "kind": "aggregate",
                "group_by": ["profile"],
                "metrics": ["mean"],
                "unit": "profile",
            },
            "presentation": {"kind": "histogram", "bins": 40},
        },
    )
    record(
        "query-ts",
        "POST",
        "/v1/query",
        body={
            **plan,
            "variables": ["temperature", "salinity", "pressure"],
            "operation": {"kind": "profiles", "limit": 3},
            "presentation": {"kind": "ts_diagram"},
        },
    )
    (OUTPUT / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(f"recorded {len(index)} fixtures under {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
