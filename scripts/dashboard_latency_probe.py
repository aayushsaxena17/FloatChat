"""Dashboard latency probe (reports/dashboard_latency_2026-10-11.md).

    python3 scripts/dashboard_latency_probe.py [http://127.0.0.1:8000]

Every aggregate uses a distinct but equal-cost plan (a different metric set), so the in-process
result memo (ADR-0067) never answers: the numbers are real executions. Run it against a freshly
restarted API (the memo is empty) after the part-cache warm-up has logged "warm_cache". It
measures five whole-quarter Indian Ocean aggregates, five Arabian Sea aggregates, the latency of
/v1/health/live while aggregates run, and a whole-quarter plus an Arabian Sea request in parallel.
"""

import itertools
import json
import sys
import threading
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
METRICS = [
    list(m)
    for r in (2, 3)
    for m in itertools.combinations(["mean", "count", "min", "max", "stddev"], r)
]
counter = itertools.count()


def plan(region, depth=None):
    p = {
        "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
        "geography": {"kind": "named_region", "value": region},
        "variables": ["temperature", "salinity"],
        "qc_policy": "science_ready",
        "operation": {
            "kind": "aggregate",
            "group_by": ["month"],
            "metrics": METRICS[next(counter) % len(METRICS)],
            "unit": "profile",
        },
        "presentation": {"kind": "table"},
    }
    if depth:
        p["depth_dbar"] = depth
    return p


def post(p):
    t = time.monotonic()
    r = urllib.request.Request(
        BASE + "/v1/query",
        data=json.dumps(p).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=120) as resp:
        body = json.loads(resp.read())
    assert not body["execution"].get("cached"), "memo hit"
    return round((time.monotonic() - t) * 1000)


def get(path):
    t = time.monotonic()
    with urllib.request.urlopen(BASE + path, timeout=60) as resp:
        resp.read()
    return round((time.monotonic() - t) * 1000)


out = {
    "whole_quarter_ms": [post(plan("Indian Ocean")) for _ in range(5)],
    "arabian_sea_ms": [post(plan("Arabian Sea", {"min": 0, "max": 100})) for _ in range(5)],
}
health, stop = [], threading.Event()


def poll():
    while not stop.is_set():
        health.append(get("/v1/health/live"))
        time.sleep(0.05)


th = threading.Thread(target=poll)
th.start()
during = [post(plan("Indian Ocean")) for _ in range(3)]
stop.set()
th.join()
out["health_live_during_uncached_aggregates_ms"] = {
    "max": max(health),
    "median": sorted(health)[len(health) // 2],
    "samples": len(health),
    "aggregates_ms": during,
}
res = {}


def par(n, p):
    res[n] = post(p)


t = time.monotonic()
ths = [
    threading.Thread(target=par, args=(n, p))
    for n, p in (
        ("whole", plan("Indian Ocean")),
        ("arabian", plan("Arabian Sea", {"min": 0, "max": 100})),
    )
]
[x.start() for x in ths]
[x.join() for x in ths]
out["parallel_pair_ms"] = {"wall": round((time.monotonic() - t) * 1000), **res}
print(json.dumps(out))
