"""Stage 5 report (ADR-0081): one ten-year request run twice through the job system.

Usage (against the running development stack):

    python scripts/stage5_report.py run --region "Arabian Sea" --start 2015-04-01 --end 2025-04-01
    python scripts/stage5_report.py report --jobs <first-job-id>,<second-job-id>

``run`` creates the export job through ``POST /v1/exports`` with a fixed client identifier,
follows it to a terminal state, and prints its id; run it twice. ``report`` reads the two jobs
through the API and the job rows' evidence and writes ``reports/historical_jobs_<date>.md``
with chunks, durations, HTTP attempts and retries, the cache reuse ratio, artefact sizes and
the PostgreSQL and object bytes the first run added. Every number comes from the API or the
database; nothing is typed by hand.
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

ROOT = Path(__file__).resolve().parents[1]
CLIENT = "stage5-report"
TERMINAL = {"completed", "partial", "cancelled", "failed"}


def api(url: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """One API call; a 5xx or a connection failure on a read is retried (the database is
    busy committing chunks while a run is in flight), a 4xx stops the script."""
    attempts = 1 if body is not None else 6
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url.rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-FloatChat-Client": CLIENT, "Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())  # type: ignore[no-any-return]
        except urllib.error.HTTPError as error:
            detail = error.read().decode()[:400]
            if error.code < 500 or attempt == attempts:
                raise SystemExit(f"{path}: HTTP {error.code} {detail}") from None
            print(f"{path}: HTTP {error.code}, retrying ({attempt}/{attempts})", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == attempts:
                raise SystemExit(f"{path}: {type(error).__name__}") from None
            print(f"{path}: {type(error).__name__}, retrying ({attempt}/{attempts})", flush=True)
        time.sleep(10 * attempt)
    raise SystemExit(f"{path}: unreachable")


def database_sizes(container: str) -> dict[str, int]:
    """PostgreSQL bytes of the scientific tables and the environment's object bytes."""
    query = (
        "SELECT json_build_object("
        "'core_measurement', pg_total_relation_size('app.core_measurement'),"
        "'argo_profile', pg_total_relation_size('app.argo_profile'),"
        "'database', pg_database_size('floatchat'),"
        "'parts', (SELECT count(*) FROM app.committed_active_partitions),"
        "'object_bytes', (SELECT coalesce(sum(bytes),0) FROM app.committed_active_partitions),"
        "'profiles', (SELECT count(*) FROM app.argo_profile),"
        "'levels', (SELECT count(*) FROM app.core_measurement))"
    )
    result = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "floatchat_admin",
            "-d",
            "floatchat",
            "-Atc",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return {key: int(value) for key, value in json.loads(result.stdout).items()}


def run(arguments: argparse.Namespace) -> int:
    body = {
        "time_range": {
            "start": arguments.start + "T00:00:00Z",
            "end": arguments.end + "T00:00:00Z",
        },
        "geography": {"kind": "named_region", "value": arguments.region},
        "depth_dbar": {"min": 0, "max": arguments.depth_max},
        "qc_policy": "science_ready",
        "format": arguments.format,
    }
    if arguments.job:
        # Resume following a job created earlier; the sizes before it were saved then.
        job_id = arguments.job
        sidecar_path = ROOT / "reports" / f"historical_job_{job_id[:8]}.json"
        previous = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
        before = previous.get("sizes_before", {})
        created = {"job": api(arguments.api_url, f"/v1/jobs/{job_id}")["job"]}
    else:
        before = database_sizes(arguments.db_container) if arguments.db_container else {}
        created = api(arguments.api_url, "/v1/exports", body)
        job_id = created["job"]["id"]
        print(
            json.dumps(
                {"job": job_id, "created": created["created"], "attached": created["attached"]}
            )
        )
        (ROOT / "reports" / f"historical_job_{job_id[:8]}.json").write_text(
            json.dumps({"job": job_id, "sizes_before": before, "request": body}, indent=2) + "\n"
        )
    started = time.monotonic()
    state = created["job"]["state"]
    while state not in TERMINAL:
        time.sleep(arguments.poll)
        detail = api(arguments.api_url, f"/v1/jobs/{job_id}")
        state = detail["job"]["state"]
        progress = detail["job"]["progress"]
        print(
            f"{datetime.now(UTC):%H:%M:%S} state={state} fetched={progress.get('fetch_complete', 0)}/"
            f"{progress.get('fetch_total', 0)} failed={progress.get('fetch_failed', 0)} "
            f"elapsed={round(time.monotonic() - started)}s",
            flush=True,
        )
    after = database_sizes(arguments.db_container) if arguments.db_container else {}
    sidecar = {
        "job": job_id,
        "state": state,
        "sizes_before": before,
        "sizes_after": after,
        "request": body,
    }
    out = ROOT / "reports" / f"historical_job_{job_id[:8]}.json"
    out.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"job": job_id, "state": state, "sidecar": str(out.relative_to(ROOT))}))
    return 0 if state in ("completed", "partial") else 1


def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        - datetime.fromisoformat(start.replace("Z", "+00:00"))
    ).total_seconds()


CLOCK_JUMP = datetime(2026, 10, 16, 0, 48, tzinfo=UTC)


def _spans_jump(start: str | None, end: str | None) -> bool:
    if not start or not end:
        return False
    started = datetime.fromisoformat(start.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return started < CLOCK_JUMP <= finished


def _fmt_bytes(value: int) -> str:
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024**3:.2f} GB"


def report(arguments: argparse.Namespace) -> int:
    jobs = [
        api(arguments.api_url, f"/v1/jobs/{job_id.strip()}") for job_id in arguments.jobs.split(",")
    ]
    sidecars = []
    for detail in jobs:
        path = ROOT / "reports" / f"historical_job_{detail['job']['id'][:8]}.json"
        sidecars.append(json.loads(path.read_text()) if path.exists() else {})
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    date = arguments.date or datetime.now(UTC).strftime("%Y-%m-%d")
    first = jobs[0]["job"]
    request = first["request"]
    lines = [
        f"# Historical jobs report ({date})",
        "",
        f"Commit `{commit}`; API `{arguments.api_url}`; client `{CLIENT}`. One export request run "
        f"{len(jobs)} times through `POST /v1/exports` (ADR-0079); every number below is read from "
        "the job rows and the ingestion runs they created.",
        "",
        "## Request",
        "",
        f"- Region: {request['geography'].get('value', request['geography'])}",
        f"- Period: {request['time_range']['start']} to {request['time_range']['end']} (exclusive)",
        f"- Depth: {request.get('depth_dbar', {}).get('min', 0)} to {request.get('depth_dbar', {}).get('max', 'all')} dbar; QC policy {request.get('qc_policy')}; format {request.get('format')}",
        "",
        "## Runs",
        "",
        "| Run | Job | State | Months × tiles | Reused | Fetch chunks | Duration (job) | Chunk time | HTTP requests | Retries | Profiles accepted |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    spanning: list[str] = []
    for index, detail in enumerate(jobs, start=1):
        job = detail["job"]
        chunks = detail["chunks"]
        fetch = [c for c in chunks if c["kind"] == "fetch"]
        attempts = sum(int(c["evidence"].get("request_attempts", 0) or 0) for c in fetch)
        retries = sum(int(c["evidence"].get("http_retries", 0) or 0) for c in fetch)
        profiles = sum(int(c["evidence"].get("accepted_profiles", 0) or 0) for c in fetch)
        duration = _seconds(job.get("started_at"), job.get("finished_at"))
        chunk_time = 0.0
        for c in chunks:
            seconds = _seconds(c.get("started_at"), c.get("finished_at"))
            if seconds is None:
                continue
            if _spans_jump(c.get("started_at"), c.get("finished_at")):
                spanning.append(f"run {index} chunk {c['seq']} ({c['label']})")
                continue
            chunk_time += seconds
        progress = job["progress"]
        lines.append(
            f"| {index} | `{job['id'][:8]}` | {job['state']} | {progress.get('slots_total')} | "
            f"{progress.get('slots_reused')} ({round(100 * float(progress.get('reuse_ratio', 0)))}%) | "
            f"{len(fetch)} ({sum(1 for c in fetch if c['state'] == 'complete')} complete, {sum(1 for c in fetch if c['state'] == 'failed')} failed) | "
            f"{'-' if duration is None else f'{duration / 60:.1f} min'} | {chunk_time / 60:.1f} min | {attempts} | {retries} | {profiles} |"
        )
    failures: list[str] = []
    for index, detail in enumerate(jobs, start=1):
        lines += [
            "",
            f"## Chunks of run {index}",
            "",
            "| Chunk | Months | State | Ingestion runs | Last run state | Termination | Leaf states | HTTP requests | Retries | Profiles | Levels | Received | Duration |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for chunk in detail["chunks"]:
            evidence = chunk["evidence"]
            duration = _seconds(chunk.get("started_at"), chunk.get("finished_at"))
            runs = evidence.get("runs") or ([evidence] if evidence.get("run_id") else [])
            jump = (
                " (spans the clock jump)"
                if _spans_jump(chunk.get("started_at"), chunk.get("finished_at"))
                else ""
            )
            lines.append(
                f"| {chunk['seq']} | {chunk['label']} | {chunk['state']} | {len(runs) if chunk['kind'] == 'fetch' else '-'} | "
                f"{evidence.get('run_state', '-')} | "
                f"{evidence.get('termination_reason') or '-'} | {json.dumps(evidence.get('leaf_states', {}))} | "
                f"{evidence.get('request_attempts', '-')} | {evidence.get('http_retries', '-')} | "
                f"{evidence.get('accepted_profiles', '-')} | {evidence.get('accepted_levels', '-')} | "
                f"{_fmt_bytes(int(evidence.get('received_bytes', 0) or 0)) if evidence.get('received_bytes') else '-'} | "
                f"{'-' if duration is None else f'{duration / 60:.1f} min'}{jump} |"
            )
            if chunk["state"] == "failed":
                error = chunk.get("error") or {}
                failures.append(
                    f"run {index} chunk {chunk['seq']} ({chunk['label']}): {error.get('code', '-')} - "
                    f"{error.get('message', '')}"
                    + (f" after {len(runs)} ingestion run(s)" if chunk["kind"] == "fetch" else "")
                    + (
                        "; it failed before the runner retried fetch chunks (one run only)"
                        if len(runs) == 1 and chunk["kind"] == "fetch"
                        else ""
                    )
                )
    lines += [
        "",
        "## Artefacts",
        "",
        "| Run | Role | File | Bytes | Rows | Profiles | SHA-256 |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, detail in enumerate(jobs, start=1):
        for artefact in detail["artefacts"]:
            lines.append(
                f"| {index} | {artefact['role']} | `{artefact['filename']}` | {artefact['bytes']} | "
                f"{artefact['row_count']} | {artefact['profile_count']} | `{artefact['sha256'][:16]}…` |"
            )
    for index, sidecar in enumerate(sidecars, start=1):
        if not (sidecar.get("sizes_before") and sidecar.get("sizes_after")):
            continue
        before, after = sidecar["sizes_before"], sidecar["sizes_after"]
        lines += [
            "",
            f"## What run {index} added to the stores",
            "",
            "| Measure | Before | After | Added |",
            "|---|---|---|---|",
        ]
        for key, label in (
            ("profiles", "Profiles in the registry"),
            ("levels", "Measurement levels in PostgreSQL"),
            ("parts", "Committed Parquet parts"),
        ):
            lines.append(f"| {label} | {before[key]} | {after[key]} | {after[key] - before[key]} |")
        for key, label in (
            ("core_measurement", "PostgreSQL bytes of core_measurement"),
            ("argo_profile", "PostgreSQL bytes of argo_profile"),
            ("database", "PostgreSQL database bytes"),
            ("object_bytes", "Object-store bytes of committed parts"),
        ):
            lines.append(
                f"| {label} | {_fmt_bytes(before[key])} | {_fmt_bytes(after[key])} | {_fmt_bytes(after[key] - before[key])} |"
            )
    missing = (jobs[-1]["job"].get("result") or {}).get("missing_slots", [])
    data_hashes = {
        artefact["sha256"]
        for detail in jobs
        for artefact in detail["artefacts"]
        if artefact["role"] == "data"
    }
    lines += [
        "",
        "## Notes",
        "",
        f"- Cache reuse ratio of run {len(jobs)}: {jobs[-1]['job']['progress'].get('reuse_ratio')} "
        "(slots reused over slots required; slots not reused are fetched, or listed as "
        "quarantined without a run).",
        f"- Missing slots after run {len(jobs)}: {len(missing)}"
        + (f" (months {sorted({m['month'] for m in missing})[:12]})" if missing else ""),
        (
            f"- The data artefacts of the runs that exported are byte-identical "
            f"(one SHA-256, `{next(iter(data_hashes))[:16]}…`): the export is deterministic "
            "over the same catalogue."
            if len(data_hashes) == 1
            and sum(1 for d in jobs for a in d["artefacts"] if a["role"] == "data") > 1
            else f"- Data artefact SHA-256 values across runs: {len(data_hashes)}."
        ),
        "- Historical months are stored in PostgreSQL and as Parquet parts alike (ADR-0078 point 4); "
        "the table above records the cost of that decision for this region.",
    ]
    for failure in failures:
        lines.append(f"- Failed chunk: {failure}.")
    for index, detail in enumerate(jobs, start=1):
        quarantined = (detail["job"].get("result") or {}).get("quarantined_slots") or []
        if quarantined:
            slots = sorted(
                {
                    f"{q['month']} {q['tile']['west']}:{q['tile']['south']}"
                    if isinstance(q.get("tile"), dict)
                    else f"{q['month']} {q.get('tile')}"
                    for q in quarantined
                }
            )
            lines.append(
                f"- Run {index}: {len(quarantined)} month-tile slot(s) quarantined by the Stage 1 "
                f"source policy (an upstream data warning quarantines the whole month-tile, "
                f"ADR-0040/0046) and not fetched again: {slots[:12]}."
            )
    if len(jobs) > 1:
        refetched = [c for c in jobs[-1]["chunks"] if c["kind"] == "fetch"]
        months = sorted({m for c in refetched for m in c["evidence"].get("months", [])})
        lines.append(
            f"- Run {len(jobs)} planned {len(refetched)} fetch chunk(s) from the catalogue for the slots "
            f"the previous run left missing"
            + (f" (months {months})" if months else "")
            + "; everything else was reused."
        )
    if spanning:
        lines.append(
            f"- The host clock jumped about seven hours at {CLOCK_JUMP.strftime('%H:%M')} UTC on "
            f"{CLOCK_JUMP.date()}; job durations that include it are not wall time. The 'Chunk time' "
            f"column sums chunk durations and leaves out {', '.join(spanning)}."
        )
    out = ROOT / "reports" / f"historical_jobs_{date}.md"
    out.write_text("\n".join(lines) + "\n")
    (ROOT / "reports" / f"historical_jobs_{date}.json").write_text(
        json.dumps(
            {"jobs": jobs, "sidecars": sidecars, "commit": commit},
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )
    print(str(out.relative_to(ROOT)))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--region", default="Arabian Sea")
    runner.add_argument("--start", default="2015-04-01")
    runner.add_argument("--end", default="2025-04-01")
    runner.add_argument("--depth-max", type=int, default=2000)
    runner.add_argument("--format", default="parquet", choices=("csv", "parquet"))
    runner.add_argument("--poll", type=float, default=30.0)
    runner.add_argument("--db-container", default="floatchat-stage0-wsl-dev-db-1")
    runner.add_argument("--job", default=None, help="follow an existing job instead")
    reporter = sub.add_parser("report")
    reporter.add_argument("--jobs", required=True, help="comma-separated job ids, first run first")
    reporter.add_argument("--date", default=None)
    arguments = parser.parse_args(argv)
    return run(arguments) if arguments.command == "run" else report(arguments)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
