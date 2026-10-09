"""Prepare an offline isolated project; execution requires separate owner opt-in.

The prepare path never reads an upstream credential. Docker output is captured,
not rendered on errors. Local service secrets remain in an ignored mode-0600 file.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/home/floatchat/FloatChat-stage1")
sys.path.insert(0, str(ROOT))
from scripts.stage1_verify import source_hash  # noqa: E402

SESSIONS = ROOT / ".cache/stage1-acceptance"
COMPOSE = ROOT / "infra/docker-compose.acceptance.yml"
LIVE_COMPOSE = ROOT / "infra/docker-compose.acceptance-live.yml"
IMAGES = {
    "API": "sha256:7055829eacc85bbc99fbbaefb735bd3ce8a916c93d4aec115ccf12ded1eccd2a",
    "DB": "sha256:d84da980fdcc9c281fffd62c626f72da7f8c78a239694bb63c60679541024d1b",
    "MINIO": "sha256:0c9f68b6e6633c942dfaba317af259e74ffbc201102eff13dd56a98e8df666ff",
}
# Worker sizing of this 3.7 GB host, written to each session's environment file and manifest
# (docker-compose.acceptance.yml documents the 8 GB production sizing: 4 workers in 4g).
TOPOLOGY = {"acquire_slots": 4, "process_workers": 2, "process_memory": "2g"}


class PreparationFailure(Exception):
    pass


def safe_environment():
    # Do not inherit credentials, Compose overrides, PYTHONPATH or Docker hosts.
    return {name: os.environ[name] for name in ("PATH", "HOME", "USER") if name in os.environ}


def command(arguments, *, timeout=120, check=True, progress_callback=None):
    if progress_callback is None:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=safe_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    else:
        # Bounded polling keeps progress visible without forwarding child output
        # or blocking on pipe buffers. Only allowlisted persisted counters print.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                arguments,
                cwd=ROOT,
                env=safe_environment(),
                stdout=output,
                stderr=subprocess.DEVNULL,
            )
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic() - started >= timeout:
                        raise PreparationFailure("acceptance_command_deadline_exceeded")
                    progress_callback()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        continue
                output.seek(0)
                data = output.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise PreparationFailure("acceptance_client_output_limit")
                result = subprocess.CompletedProcess(
                    arguments, process.returncode, data.decode(), ""
                )
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    if check and result.returncode:
        raise PreparationFailure("local_command_failed_no_sensitive_diagnostics")
    return result


def git_head():
    """Short commit recorded with each session; the source hash binds the exact files."""
    head = command(["git", "rev-parse", "--short=12", "HEAD"]).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{12}", head) is None:
        raise PreparationFailure("invalid_git_head")
    return head


def session_directory(identifier):
    if re.fullmatch(r"[a-f0-9]{16}", identifier) is None:
        raise PreparationFailure("invalid_acceptance_session")
    return SESSIONS / identifier


def compose(identifier, *arguments, live=False, timeout=120, check=True, progress_callback=None):
    directory = session_directory(identifier)
    args = [
        "docker",
        "compose",
        "--project-directory",
        str(directory),
        "--env-file",
        str(directory / "environment.env"),
        "-p",
        "floatchat-s1-acceptance-" + identifier,
        "-f",
        str(COMPOSE),
    ]
    if live:
        args += ["-f", str(LIVE_COMPOSE)]
    options = {"timeout": timeout, "check": check}
    if progress_callback is not None:
        options["progress_callback"] = progress_callback
    return command(args + list(arguments), **options)


@contextmanager
def uninterrupted_cleanup():
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def stop_acceptance(identifier, project):
    """Stop service and one-off containers; retain all objects and databases."""
    failures = []
    with uninterrupted_cleanup():
        print("acceptance_cleanup_stopping_isolated_containers_preserving_data", flush=True)
        try:
            command(["docker", "stop", "--time", "10", project + "-live-owner"], check=False)
        except Exception:
            failures.append("live_worker_stop_unavailable")
        try:
            compose(identifier, "stop", "--timeout", "10", live=True, check=False)
        except Exception:
            failures.append("service_stop_unavailable")
        try:
            containers = command(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                ]
            ).stdout.split()
            if len(containers) > 16:
                raise PreparationFailure("unexpected_acceptance_container_count")
            for container in containers:
                if re.fullmatch(r"[a-f0-9]{12,64}", container) is None:
                    raise PreparationFailure("unexpected_container_identifier")
            if containers:
                command(["docker", "stop", "--time", "10", *containers], timeout=30)
            remaining = command(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                ]
            ).stdout.strip()
            if remaining:
                failures.append("isolated_containers_still_running")
        except Exception:
            failures.append("container_stop_verification_unavailable")
    return failures


def print_progress(identifier, request, phase):
    try:
        data = json_line(
            compose(
                identifier,
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "client",
                "python",
                "scripts/stage1_acceptance_runtime.py",
                "progress",
                "--request-id",
                request,
                timeout=25,
            ).stdout
        )
        state = data.get("state")
        if state not in {
            "awaiting_admission",
            "planned",
            "fetching",
            "landed",
            "validating",
            "publishing",
            "complete",
            "partial",
            "failed",
            "quarantined",
        }:
            raise PreparationFailure("unexpected_progress_state")
        counts = data["leaf_states"]
        allowed = {
            "planned",
            "fetching",
            "landed",
            "validating",
            "publishing",
            "complete",
            "quarantined",
            "failed",
        }
        if set(counts) - allowed or any(
            type(n) is not int or not 0 <= n <= 16384 for n in counts.values()
        ):
            raise PreparationFailure("unexpected_progress_counts")
        complete = counts.get("complete", 0)
        failed = counts.get("failed", 0)
        quarantined = counts.get("quarantined", 0)
        # Queue depth per ticket kind (stage1-v4); absent from older runtime output.
        tickets = data.get("tickets", {})
        if set(tickets) - {"acquire", "process"} or any(
            set(item) != {"queued", "started"}
            or any(type(n) is not int or not 0 <= n <= 1048576 for n in item.values())
            for item in tickets.values()
        ):
            raise PreparationFailure("unexpected_progress_tickets")
        queued = "".join(
            f" {kind}_queued={tickets[kind]['queued']}"
            for kind in ("acquire", "process")
            if kind in tickets
        )
        print(
            f"acceptance_{phase}: state={state} chunks={sum(counts.values())} "
            f"complete={complete} failed={failed} quarantined={quarantined}{queued}",
            flush=True,
        )
    except Exception:
        print(f"acceptance_{phase}: progress_temporarily_unavailable", flush=True)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def json_line(output):
    for line in reversed(output.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise PreparationFailure("missing_persisted_evidence")


def inspection(identifier):
    project = "floatchat-s1-acceptance-" + identifier
    ids = command(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project]
    ).stdout.split()
    mounts = []
    services = []
    for container in ids:

        def field(template, container_id=container):
            return json.loads(
                command(["docker", "inspect", "--format", template, container_id]).stdout
            )

        labels = field("{{json .Config.Labels}}")
        assert labels["com.docker.compose.project"] == project
        service = labels["com.docker.compose.service"]
        ports = field("{{json .HostConfig.PortBindings}}")
        assert not ports
        networks = field("{{json .NetworkSettings.Networks}}")
        assert set(networks) == {project + "_default"}
        rows = field("{{json .Mounts}}")
        for row in rows:
            if row["Type"] == "volume":
                assert row["Name"].startswith(project + "_")
                mounts.append(row["Name"])
            else:
                if row["Source"].startswith(str(ROOT)):
                    assert not row["RW"]
                assert row["Source"].startswith(str(ROOT)) or row["Source"].startswith(
                    str(Path.home() / ".local/share/floatchat/stage1-acceptance" / identifier)
                )
        services.append(service)
    assert {"db", "minio", "acquire", "process", "supervisor"}.issubset(services)
    internal = command(
        ["docker", "network", "inspect", project + "_default", "--format", "{{json .Internal}}"]
    ).stdout.strip()
    assert internal == "true"
    # Compare actual identities of every other project's volume resources, without
    # reading container environments or development database/object contents.
    all_volumes = command(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.split()
    other_volumes = [name for name in all_volumes if not name.startswith(project + "_")]
    assert not set(mounts).intersection(other_volumes)
    development_volumes = []
    for development in ("floatchat-stage0-wsl-dev", "floatchat-dev"):
        containers = command(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + development]
        ).stdout.split()
        for container in containers:
            rows = json.loads(
                command(["docker", "inspect", "--format", "{{json .Mounts}}", container]).stdout
            )
            development_volumes.extend(row["Name"] for row in rows if row["Type"] == "volume")
    assert not set(mounts).intersection(development_volumes)
    return {
        "project": project,
        "services": sorted(services),
        "volumes": sorted(set(mounts)),
        "network": project + "_default",
        "network_internal": True,
        "host_port_bindings": [],
        "other_volume_count": len(other_volumes),
        "shared_development_volumes": [],
        "development_volume_identities": sorted(set(development_volumes)),
        "live_network_created": False,
    }


def start_sampler(directory, project):
    """Background cgroup sampler of the worker containers (ADR-0042 evidence); best effort."""
    for name in ("memory.stop", "memory.json"):
        (directory / name).unlink(missing_ok=True)
    try:
        return subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/stage1_memory_sampler.py"),
                "--project",
                project,
                "--output",
                str(directory / "memory.json"),
                "--stop-file",
                str(directory / "memory.stop"),
                "--max-seconds",
                "87000",
            ],
            cwd=ROOT,
            env=safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def stop_sampler(directory, sampler):
    """Stop the sampler and return its per-container summary (None: it never ran)."""
    if sampler is None:
        return None
    try:
        (directory / "memory.stop").touch()
        try:
            sampler.wait(timeout=30)
        except subprocess.TimeoutExpired:
            sampler.terminate()
            sampler.wait(timeout=30)
        report = json.loads((directory / "memory.json").read_text())
        save(ROOT / "reports/stage1-acceptance-memory.json", report)
        return {
            "available": True,
            "pass": report["pass"],
            "samples": report["samples"],
            "by_service": report["by_service"],
        }
    except Exception:
        return {"available": False}


def running_services(identifier, *names):
    """The given services that have a running container now, in the order given."""
    return [
        name
        for name in names
        if compose(identifier, "ps", "--status", "running", "-q", name).stdout.strip()
    ]


def prepare():
    if Path.cwd().resolve() != ROOT or ROOT.resolve() != ROOT:
        raise PreparationFailure("fresh_wsl_checkout_required")
    for image in IMAGES.values():
        assert (
            command(["docker", "image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip()
            == image
        )
    identifier = secrets.token_hex(8)
    directory = session_directory(identifier)
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    project = "floatchat-s1-acceptance-" + identifier
    private = (
        Path.home() / ".local/share/floatchat/stage1-acceptance" / identifier / "worker-private"
    )
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    database = "floatchat_s1_" + identifier
    admin_password, worker_password = secrets.token_hex(24), secrets.token_hex(24)
    environment = {
        "COMPOSE_PROJECT_NAME": project,
        "ACCEPTANCE_DATABASE": database,
        "ACCEPTANCE_UID": str(os.getuid()),
        "ACCEPTANCE_GID": str(os.getgid()),
        "ACCEPTANCE_PRIVATE_DIRECTORY": str(private),
        "DB_ADMIN_PASSWORD": admin_password,
        "ACCEPTANCE_DB_PASSWORD": worker_password,
        "DATABASE_ADMIN_URL": f"postgresql://floatchat_admin:{admin_password}@db:5432/{database}",
        "INGESTION_DATABASE_URL": f"postgresql://acceptance_ingestion:{worker_password}@db:5432/{database}",
        "INGESTION_ENVIRONMENT_ID": str(uuid.uuid4()),
        "INGESTION_BUCKET": project,
        "ACCEPTANCE_CONTROL_BUCKET": project + "-control",
        "INGESTION_QUEUE_NAMESPACE": project + ".ingestion",
        "ACCEPTANCE_ACQUIRE_SLOTS": str(TOPOLOGY["acquire_slots"]),
        "ACCEPTANCE_PROCESS_WORKERS": str(TOPOLOGY["process_workers"]),
        "ACCEPTANCE_PROCESS_MEMORY": TOPOLOGY["process_memory"],
        "OBJECT_STORAGE_ACCESS_KEY": "acceptance-" + identifier,
        "OBJECT_STORAGE_SECRET_KEY": secrets.token_hex(24),
        "MINIO_ROOT_USER": "acceptance-admin-" + identifier,
        "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
        "INGESTION_APPLICATION_COMMIT": git_head() + "+worktree:" + source_hash(),
        **{"ACCEPTANCE_" + key + "_IMAGE": image for key, image in IMAGES.items()},
    }
    env_file = directory / "environment.env"
    descriptor = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(key + "=" + value for key, value in environment.items()) + "\n")
    manifest = {
        "session": identifier,
        "project": project,
        "database": database,
        "bucket": project,
        "queue": environment["INGESTION_QUEUE_NAMESPACE"],
        "worker_topology": {
            **TOPOLOGY,
            "acquire_memory": "1g",
            "worker_memory_bytes": 1024**3,
            "services": ["acquire", "process", "supervisor"],
        },
        "environment_id": environment["INGESTION_ENVIRONMENT_ID"],
        "images": IMAGES,
        "source_sha256": source_hash(),
        "environment_file_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
        "live_request_id": str(uuid.uuid4()),
        "replay_request_id": str(uuid.uuid4()),
        "reference_time_utc": "2025-04-01T00:00:00Z",
        "interval": ["2025-01-01T00:00:00Z", "2025-04-01T00:00:00Z"],
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "live_executed": False,
    }
    save(directory / "manifest.json", manifest)
    try:
        compose(identifier, "config", "--quiet")
        compose(identifier, "config", "--quiet", live=True)
        compose(
            identifier,
            "up",
            "-d",
            "--pull",
            "never",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "90",
            "db",
            "minio",
        )
        compose(identifier, "run", "--rm", "-T", "--no-deps", "db-init")
        compose(identifier, "run", "--rm", "-T", "--no-deps", "storage-init")
        compose(
            identifier,
            "up",
            "-d",
            "--pull",
            "never",
            "--no-build",
            "acquire",
            "process",
            "supervisor",
        )
        proof = json_line(
            compose(identifier, "run", "--rm", "-T", "--no-deps", "client", timeout=120).stdout
        )
        # Both queue workers start offline (no key, empty queue) and must still be up once the
        # proof has run: a failed configuration or slot check ends them within seconds.
        running = running_services(identifier, "acquire", "process", "supervisor")
        if running != ["acquire", "process", "supervisor"]:
            raise PreparationFailure("acceptance_worker_not_running")
        evidence = {
            **manifest,
            "isolation": inspection(identifier),
            "runtime_proof": proof,
            "workers_running_after_proof": running,
            "scope": "offline preparation only; no ingestion or upstream calls",
            "full_acceptance": "pending_owner_opt_in",
            "actual_head_CI": "pending",
        }
    finally:
        compose(identifier, "stop", "--timeout", "15", check=False)
    evidence["services_stopped"] = not compose(
        identifier, "ps", "--status", "running", "-q"
    ).stdout.strip()
    assert evidence["services_stopped"]
    save(directory / "preparation.json", evidence)
    save(ROOT / "reports/stage1-acceptance-preparation.json", evidence)
    print(
        json.dumps(
            {
                "session": identifier,
                "category": "isolated_preparation_passed",
                "services_stopped": True,
                "live_executed": False,
            }
        )
    )


def validate_report(report, *, replay=False):
    assert report["closed"] and report["state"] == "complete"
    assert report["coverage"]["proved_complete"] and not report["coverage"]["gaps"]
    assert report["full_snapshot_balanced"] and report["run_eligible_balanced"]
    assert report["scientific_level_delta_balanced"]
    assert all(row["state"] == "complete" for row in report["chunks"] if row["leaf"])
    assert report["reference_time_utc"] == "2025-04-01 00:00:00+00:00"
    # stage1-v3 (ADR-0040): qualified delivered population, never source completeness.
    assert report["contract"] == "stage1-v3"
    assert report["source_policy"]["policy"] == "S1-SOURCE-2"
    assert report["source_policy"]["scientific_source_complete"] is not True
    assert (report["source_policy"]["source_exclusion_count"] > 0) == (
        report["source_policy"]["acceptance_qualification"]
        == "acceptance_qualified_with_source_exclusions"
    )
    requested = report["coverage"]["requested"]
    assert datetime.fromisoformat(requested["start"]) == datetime(2025, 1, 1, tzinfo=UTC)
    assert datetime.fromisoformat(requested["end"]) == datetime(2025, 4, 1, tzinfo=UTC)
    if replay:
        assert report["scientific_no_change"] and report["active_partition_no_change"]


def execute(identifier, opt_in):
    if not opt_in:
        raise PreparationFailure("separate_owner_live_opt_in_required")
    directory = session_directory(identifier)
    manifest = json.loads((directory / "manifest.json").read_text())
    proof = json.loads((directory / "preparation.json").read_text())
    assert manifest["session"] == identifier and proof["services_stopped"]
    assert manifest["source_sha256"] == source_hash()
    env_file = directory / "environment.env"
    assert not env_file.is_symlink() and env_file.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(env_file.read_bytes()).hexdigest() == manifest["environment_file_sha256"]
    # This branch is exclusively owner-run after separate authorization.
    key = os.environ.get("ARGOVIS_API_KEY")
    if not key:
        raise PreparationFailure("ARGOVIS_API_KEY")
    if len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise PreparationFailure("invalid_owner_credential")
    worker = None
    worker_log = None
    sampler = None
    live_run = None
    try:
        compose(
            identifier,
            "up",
            "-d",
            "--pull",
            "never",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "90",
            "db",
            "minio",
        )
        # An offline acquire process would claim and fail upstream tickets: it stays down
        # while the live one runs.
        compose(identifier, "stop", "acquire")
        # Compose launches the live acquire process, but never receives the key in its env,
        # argv or configuration. Only container stdin transfers it into memory. The process
        # pool and supervisor start without it, on the internal network only.
        live_args = [
            "docker",
            "compose",
            "--project-directory",
            str(directory),
            "--env-file",
            str(directory / "environment.env"),
            "-p",
            manifest["project"],
            "-f",
            str(COMPOSE),
            "-f",
            str(LIVE_COMPOSE),
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--name",
            manifest["project"] + "-live-owner",
            "live-acquire",
        ]
        worker_log = open(
            directory / "owner-worker.log",
            "w",
            opener=lambda path, flags: os.open(path, flags, 0o600),
        )
        worker = subprocess.Popen(
            live_args,
            cwd=ROOT,
            env=safe_environment(),
            stdin=subprocess.PIPE,
            stdout=worker_log,
            stderr=worker_log,
            text=True,
        )
        worker.stdin.write(key + "\n")
        worker.stdin.close()
        del key
        compose(identifier, "up", "-d", "--pull", "never", "--no-build", "process", "supervisor")
        # Per-container anonymous peaks and oom counters of acquire and process, sampled from
        # the host cgroups for the whole live and replay phases.
        sampler = start_sampler(directory, manifest["project"])
        for phase in ("live", "replay"):
            print(
                f"acceptance_{phase}_starting; per_run_budget_seconds=43200; "
                "Ctrl+C stops services and preserves committed science",
                flush=True,
            )
            args = [
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "-e",
                "FLOATCHAT_LIVE_INGESTION_ENABLED=true",
                "client",
                "python",
                "scripts/stage1_acceptance_runtime.py",
                "ingest",
                "--request-id",
                manifest[phase + "_request_id"],
            ]
            if phase == "replay":
                assert live_run is not None
                # Remove the upstream acquire process before replay. Replay's acquire and
                # process containers cannot read a credential and have only the internal
                # Docker network.
                command(["docker", "stop", "--time", "15", manifest["project"] + "-live-owner"])
                compose(
                    identifier, "up", "-d", "--pull", "never", "--no-build", "acquire", "process"
                )
                args += ["--replay-run", live_run]

            def progress_update(phase=phase):
                if phase == "live" and worker.poll() is not None:
                    raise PreparationFailure("acceptance_live_worker_exited")
                print_progress(identifier, manifest[phase + "_request_id"], phase)

            result = compose(
                identifier, *args, timeout=43500, check=False, progress_callback=progress_update
            )
            admission = json_line(result.stdout)
            run = admission["run_id"]
            report = json_line(
                compose(
                    identifier,
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "client",
                    "python",
                    "scripts/stage1_acceptance_runtime.py",
                    "report",
                    "--run-id",
                    run,
                ).stdout
            )
            save(ROOT / ("reports/stage1-acceptance-" + phase + ".json"), report)
            if result.returncode:
                raise PreparationFailure("acceptance_run_incomplete_persisted_report_available")
            validate_report(report, replay=phase == "replay")
            live_run = run
        memory = stop_sampler(directory, sampler)
        sampler = None
        save(
            ROOT / "reports/stage1-acceptance-owner-result.json",
            {
                "session": identifier,
                "live_and_replay_runs_complete": True,
                "worker_topology": manifest.get("worker_topology"),
                "memory_evidence": memory,
                "full_contract_gate": "pending_review_and_actual_head_CI",
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "stage2": "blocked",
            },
        )
        print("live_and_captured_replay_evidence_ready_for_review")
    finally:
        with uninterrupted_cleanup():
            failures = stop_acceptance(identifier, manifest["project"])
            memory = stop_sampler(directory, sampler)
            if worker is not None:
                try:
                    worker.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    worker.terminate()
                    worker.wait(timeout=30)
            if worker_log is not None:
                worker_log.close()
            save(
                directory / "last-cleanup.json",
                {
                    "checked_at_utc": datetime.now(UTC).isoformat(),
                    "failures": failures,
                    "memory_evidence": memory,
                    "data_preserved": True,
                    "run_not_automatically_cancelled": True,
                },
            )
            print(
                "acceptance_cleanup_complete"
                if not failures
                else "acceptance_cleanup_incomplete_check_isolated_container_status",
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute"))
    parser.add_argument("--session")
    parser.add_argument("--live-opt-in", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.live_opt_in or args.session:
            raise PreparationFailure("invalid_preparation_arguments")
        prepare()
    else:
        execute(args.session or "", args.live_opt_in)


if __name__ == "__main__":
    # Direct script invocation must expose the repository namespace, not a host
    # shell PYTHONPATH. uv's Python cwd includes the fresh checkout.
    try:
        main()
    except PreparationFailure as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(5) from None
    except KeyboardInterrupt:
        print(
            "acceptance_interrupted_data_preserved_not_a_success; persisted_run_budgets_unchanged",
            file=sys.stderr,
        )
        raise SystemExit(130) from None
    except Exception:
        print("acceptance_failed_no_sensitive_diagnostics", file=sys.stderr)
        raise SystemExit(5) from None
