"""Read-only worker memory evidence for ADR-0042 during an acceptance session.

Polls host cgroup v2 files (cgroupfs driver: /sys/fs/cgroup/docker/<id>/) for every
running container of one Compose project whose service is a worker: the acquire process
(`acquire`, or `live-acquire` while the key is held) and the process pool (`process`).
Records per container: memory.max, peak anonymous bytes (memory.stat anon), the kernel
page-cache-inclusive memory.peak, and oom/oom_kill counters, and summarises them per
service. Never execs into a container, reads environment, logs or credentials. Stops when
the stop file appears or after --max-seconds, and writes one JSON report.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup/docker")
GIB = 1024**3
ACQUIRE_SERVICES = {"acquire", "live-acquire"}
WORKER_SERVICES = ACQUIRE_SERVICES | {"process"}


def containers(project: str) -> dict[str, tuple[str, str]]:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            '{{.ID}} {{.Label "com.docker.compose.service"}} {{.Names}}',
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    found = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in WORKER_SERVICES:
            found[parts[0]] = (parts[1], parts[2])
    return found


def read(identifier: str) -> dict[str, int] | None:
    base = CGROUP / identifier
    try:
        events = dict(line.split() for line in (base / "memory.events").read_text().splitlines())
        stat = dict(line.split() for line in (base / "memory.stat").read_text().splitlines())
        limit = (base / "memory.max").read_text().strip()
        peak = int((base / "memory.peak").read_text().strip())
    except (OSError, ValueError):
        return None
    return {
        "memory_max": -1 if limit == "max" else int(limit),
        "anon": int(stat["anon"]),
        "memory_peak": peak,
        "oom": int(events.get("oom", 0)),
        "oom_kill": int(events.get("oom_kill", 0)),
    }


def passes(entry: dict[str, object]) -> bool:
    """Per-container criterion (ADR-0042 as amended for the queue topology).

    The acquire process runs in a 1 GiB cgroup. The process container holds M single-use
    workers, each bounded to 1 GiB by RLIMIT_DATA (invisible to cgroup counters), so its
    limit is configured (2g on the 3.7 GB host, 4g in production) and only has to be finite.
    Either way: no oom events and an anonymous peak below the container's limit.
    """
    limit = int(entry["memory_max"])
    fixed = entry["service"] in ACQUIRE_SERVICES
    return (
        (limit == GIB if fixed else limit > 0)
        and int(entry["oom"]) == 0
        and int(entry["oom_kill"]) == 0
        and int(entry["anon_peak_bytes"]) < limit
    )


def summary(workers: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    """Per-service maxima over its containers (the live and offline acquire are one service)."""
    result: dict[str, dict[str, int]] = {}
    for entry in workers:
        row = result.setdefault(
            str(entry["service"]),
            {
                "containers": 0,
                "memory_max": 0,
                "anon_peak_bytes": 0,
                "memory_peak_counter_bytes": 0,
                "oom": 0,
                "oom_kill": 0,
                "samples": 0,
            },
        )
        row["containers"] += 1
        row["samples"] += int(entry["samples"])
        for key in (
            "memory_max",
            "anon_peak_bytes",
            "memory_peak_counter_bytes",
            "oom",
            "oom_kill",
        ):
            row[key] = max(row[key], int(entry[key]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-seconds", type=float, default=8 * 3600)
    args = parser.parse_args()
    started = datetime.now(UTC)
    deadline = time.monotonic() + args.max_seconds
    seen: dict[str, dict[str, object]] = {}
    samples = 0
    while time.monotonic() < deadline and not Path(args.stop_file).exists():
        for identifier, (service, name) in containers(args.project).items():
            values = read(identifier)
            if values is None:
                continue
            samples += 1
            entry = seen.setdefault(
                identifier,
                {
                    "container": f"{service}:{name}",
                    "service": service,
                    "memory_max": values["memory_max"],
                    "anon_peak_bytes": 0,
                    "memory_peak_counter_bytes": 0,
                    "oom": 0,
                    "oom_kill": 0,
                    "samples": 0,
                },
            )
            entry["samples"] = int(entry["samples"]) + 1
            for key, source in (
                ("anon_peak_bytes", "anon"),
                ("memory_peak_counter_bytes", "memory_peak"),
                ("oom", "oom"),
                ("oom_kill", "oom_kill"),
            ):
                entry[key] = max(int(entry[key]), values[source])
        time.sleep(args.interval)
    workers = list(seen.values())
    report = {
        "kind": "stage1_worker_memory_evidence",
        "criterion": "ADR-0042 (queue topology): acquire memory.max = 1 GiB, process memory.max "
        "finite (each of its workers bounded to 1 GiB by RLIMIT_DATA), zero oom/oom_kill, "
        "anonymous peak below the container's memory.max",
        "scope": "Sampled host cgroup v2 counters; anonymous peak is the maximum sample, "
        "memory.peak is the kernel high-water mark including page cache",
        "project": args.project,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "interval_seconds": args.interval,
        "samples": samples,
        "workers": workers,
        "by_service": summary(workers),
        # Evidence needs both halves of the topology to have been sampled.
        "pass": {entry["service"] for entry in workers} >= {"process"}
        and bool({entry["service"] for entry in workers} & ACQUIRE_SERVICES)
        and all(passes(entry) for entry in workers),
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in ("samples", "pass")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
