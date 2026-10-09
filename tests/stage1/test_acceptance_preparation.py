"""Offline guards for acceptance preparation; no upstream or credential access."""

import copy
import hashlib
import io
import json
import re
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import stage1_acceptance as acceptance
from scripts import stage1_acceptance_runtime as runtime
from scripts import stage1_memory_sampler as sampler

CHECKOUT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def checkout_paths(monkeypatch):
    # The real commands are pinned to the WSL checkout path; tests read this
    # repository's files and run from wherever it is checked out (e.g. CI).
    monkeypatch.setattr(acceptance, "ROOT", CHECKOUT)
    monkeypatch.setattr(acceptance, "COMPOSE", CHECKOUT / "infra/docker-compose.acceptance.yml")
    monkeypatch.setattr(
        acceptance, "LIVE_COMPOSE", CHECKOUT / "infra/docker-compose.acceptance-live.yml"
    )


def test_prepare_environment_excludes_credentials_and_compose_overrides(monkeypatch):
    monkeypatch.setenv("ARGOVIS_API_KEY", "synthetic-sensitive-sentinel")
    monkeypatch.setenv("COMPOSE_FILE", "unexpected-project.yml")
    monkeypatch.setenv("DOCKER_HOST", "tcp://unexpected.invalid:2375")
    monkeypatch.setenv("PYTHONPATH", "/unexpected")
    env = acceptance.safe_environment()
    assert set(env).issubset({"PATH", "HOME", "USER"})
    assert "synthetic-sensitive-sentinel" not in str(env)


@pytest.mark.parametrize("identifier", ["../development", "", "a" * 17, "DEADBEEF12345678"])
def test_unapproved_session_paths_rejected(identifier):
    with pytest.raises(acceptance.PreparationFailure, match="invalid_acceptance_session"):
        acceptance.session_directory(identifier)


def test_execute_without_owner_opt_in_never_accesses_environment(monkeypatch):
    class DeniedEnvironment:
        def get(self, *args):
            pytest.fail("environment accessed before owner opt-in")

    monkeypatch.setattr(acceptance, "os", SimpleNamespace(environ=DeniedEnvironment()))
    with pytest.raises(acceptance.PreparationFailure, match="separate_owner_live_opt_in_required"):
        acceptance.execute("0123456789abcdef", False)


@pytest.mark.parametrize(
    "command", ["proof", "process", "supervise", "ingest", "report", "progress", "compact"]
)
def test_runtime_stdin_credential_refused_outside_live_acquire(monkeypatch, command):
    # Only `acquire --stdin-key` may read the key; it is refused before stdin is touched.
    monkeypatch.setenv("FLOATCHAT_LIVE_INGESTION_ENABLED", "true")
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "argv", ["runtime", command, "--stdin-key"])
    with pytest.raises(runtime.Rejection, match="live_acceptance_opt_in_required"):
        runtime.main()


def test_runtime_acquire_stdin_credential_refused_while_live_disabled(monkeypatch):
    monkeypatch.delenv("FLOATCHAT_LIVE_INGESTION_ENABLED", raising=False)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "argv", ["runtime", "acquire", "--stdin-key"])
    with pytest.raises(runtime.Rejection, match="live_acceptance_opt_in_required"):
        runtime.main()


def test_runtime_live_acquire_reads_the_key_from_stdin_only(monkeypatch):
    seen = []
    monkeypatch.setenv("ARGOVIS_API_KEY", "placeholder")  # restored on teardown
    monkeypatch.setenv("FLOATCHAT_LIVE_INGESTION_ENABLED", "true")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"synthetic-key-0123\n")))
    monkeypatch.setattr(sys, "argv", ["runtime", "acquire", "--stdin-key"])
    monkeypatch.setattr(
        runtime, "acquire", lambda: seen.append(runtime.os.environ["ARGOVIS_API_KEY"]) or 0
    )
    with pytest.raises(SystemExit) as stopped:
        runtime.main()
    assert stopped.value.code == 0 and seen == ["synthetic-key-0123"]


@pytest.mark.parametrize("key", [b"\n", b"has space\n", b"x" * 4097 + b"\n"])
def test_runtime_rejects_malformed_owner_credentials(monkeypatch, key):
    monkeypatch.setenv("FLOATCHAT_LIVE_INGESTION_ENABLED", "true")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(key)))
    monkeypatch.setattr(sys, "argv", ["runtime", "acquire", "--stdin-key"])
    with pytest.raises(runtime.Rejection, match="invalid_owner_credential"):
        runtime.main()


def test_runtime_acquire_and_process_run_the_worker_entry_points(monkeypatch):
    import floatchat_workers.acquire as acquire_module
    import floatchat_workers.process as process_module

    calls = []
    monkeypatch.setattr(acquire_module, "main", lambda slots: calls.append(("acquire", slots)) or 0)
    monkeypatch.setattr(
        process_module, "main", lambda workers: calls.append(("process", workers)) or 0
    )
    monkeypatch.setattr(
        runtime.Configuration,
        "load",
        classmethod(lambda cls: SimpleNamespace(acquire_slots=3, process_workers=2)),
    )
    monkeypatch.delenv("ARGOVIS_API_KEY", raising=False)
    for command in ("acquire", "process"):
        monkeypatch.setattr(sys, "argv", ["runtime", command])
        with pytest.raises(SystemExit) as stopped:
            runtime.main()
        assert stopped.value.code == 0
    assert calls == [("acquire", 3), ("process", 2)]
    assert "ARGOVIS_API_KEY" not in runtime.os.environ


INGEST = [
    "ingest",
    "--mode",
    "acceptance",
    "--region",
    "indian-ocean",
    "--from",
    "2025-01",
    "--to",
    "2025-03",
    "--execution-seconds",
    "43200",
    "--request-id",
    "r1",
]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["supervise"], ["supervise"]),
        (["compact"], ["compact"]),
        (["compact", "--seconds", "30"], ["compact", "--seconds", "30"]),
        (["ingest", "--request-id", "r1"], [*INGEST, "--live-opt-in"]),
        (
            ["ingest", "--request-id", "r1", "--replay-run", "p1"],
            [*INGEST, "--replay-run", "p1"],
        ),
    ],
)
def test_runtime_forwards_supervise_compact_and_ingest_to_the_cli(monkeypatch, argv, expected):
    import floatchat_workers.cli as cli_module

    forwarded = []
    monkeypatch.setattr(cli_module, "main", lambda arguments: forwarded.append(arguments) or 0)
    monkeypatch.setattr(sys, "argv", ["runtime", *argv])
    with pytest.raises(SystemExit) as stopped:
        runtime.main()
    assert stopped.value.code == 0 and forwarded == [expected]


def test_runtime_has_no_celery_or_redis():
    text = (CHECKOUT / "scripts/stage1_acceptance_runtime.py").read_text().lower()
    assert "celery" not in text and "redis" not in text and "floatchat_workers.app" not in text
    assert not hasattr(runtime, "configure_broker")


def test_runtime_migration_head_is_the_newest_migration():
    heads = sorted(
        (
            path.name,
            re.search(r'^revision = "([^"]+)"', path.read_text(), re.MULTILINE).group(1),
        )
        for path in (CHECKOUT / "infra/migrations/versions").glob("*.py")
    )
    assert runtime.MIGRATION_HEAD == heads[-1][1]


def test_images_have_no_redis_pin():
    assert set(acceptance.IMAGES) == {"API", "DB", "MINIO"}


def compose_services():
    return yaml.safe_load(acceptance.COMPOSE.read_text())["services"]


def commands(*files):
    result = []
    for path in files:
        for service in yaml.safe_load(path.read_text())["services"].values():
            result.append(service.get("command", []))
    return result


def test_compose_has_private_resources_no_ports_or_beat_and_separate_egress():
    configuration = yaml.safe_load(acceptance.COMPOSE.read_text())
    assert configuration["networks"] == {"default": {"internal": True}}
    assert set(configuration["volumes"]) == {"postgres_data", "minio_data"}
    assert not any(value.get("external") for value in configuration["volumes"].values())
    for name, service in configuration["services"].items():
        assert "ports" not in service and "ARGOVIS_API_KEY" not in str(service)
        assert "beat" not in name and service["pull_policy"] == "never"
        assert "networks" not in service
    live = yaml.safe_load(acceptance.LIVE_COMPOSE.read_text())
    assert set(live["services"]) == {"live-acquire"}
    assert live["services"]["live-acquire"]["networks"] == ["default", "upstream"]
    assert live["services"]["live-acquire"]["profiles"] == ["live"]
    assert live["networks"] == {"upstream": {"internal": False}}
    assert "ARGOVIS_API_KEY" not in str(live)


def test_compose_runs_the_queue_topology_without_celery_or_redis():
    services = compose_services()
    assert set(services) == {
        "db",
        "minio",
        "db-init",
        "storage-init",
        "acquire",
        "process",
        "supervisor",
        "client",
    }
    text = acceptance.COMPOSE.read_text() + acceptance.LIVE_COMPOSE.read_text()
    assert "redis" not in text.lower() and "celery" not in text.lower()
    for service in services.values():
        assert not {"INGESTION_REDIS_URL", "REDIS_URL", "ACCEPTANCE_REDIS_PREFIX"} & set(
            service.get("environment", {})
        )
    # Limits and sizing as documented in the compose comment: 3.7 GB host values are defaults.
    assert services["db"]["mem_limit"] == "1g" and services["minio"]["mem_limit"] == "512m"
    acquire, process = services["acquire"], services["process"]
    assert acquire["command"] == ["python", "scripts/stage1_acceptance_runtime.py", "acquire"]
    assert acquire["mem_limit"] == "1g"
    assert acquire["environment"]["INGESTION_ACQUIRE_SLOTS"] == "${ACCEPTANCE_ACQUIRE_SLOTS:-4}"
    assert process["command"] == ["python", "scripts/stage1_acceptance_runtime.py", "process"]
    assert process["mem_limit"] == "${ACCEPTANCE_PROCESS_MEMORY:-2g}"
    assert process["environment"]["INGESTION_PROCESS_WORKERS"] == "${ACCEPTANCE_PROCESS_WORKERS:-2}"
    assert process["environment"]["INGESTION_WORKER_MEMORY_BYTES"] == "1073741824"
    assert "INGESTION_PROCESS_WORKERS" not in acquire["environment"]
    assert "INGESTION_ACQUIRE_SLOTS" not in process["environment"]
    for service in (acquire, process, services["supervisor"]):
        assert service["environment"]["FLOATCHAT_LIVE_INGESTION_ENABLED"] == "false"
        assert service["user"] == "${ACCEPTANCE_UID:?}:${ACCEPTANCE_GID:?}"
        assert service["volumes"][0].endswith(":ro")
        assert service["volumes"][1] == "${ACCEPTANCE_PRIVATE_DIRECTORY:?}:/home/acceptance/private"
    assert "worker" not in services


def test_session_sizing_matches_the_compose_defaults():
    text = acceptance.COMPOSE.read_text()
    defaults = dict(re.findall(r"\$\{(ACCEPTANCE_[A-Z_]+):-(\w+)\}", text))
    assert defaults == {
        "ACCEPTANCE_ACQUIRE_SLOTS": str(acceptance.TOPOLOGY["acquire_slots"]),
        "ACCEPTANCE_PROCESS_MEMORY": acceptance.TOPOLOGY["process_memory"],
        "ACCEPTANCE_PROCESS_WORKERS": str(acceptance.TOPOLOGY["process_workers"]),
    }


def test_only_the_live_acquire_command_carries_the_stdin_key_flag():
    # Neither the offline acquire, the process pool nor the supervisor ever reads the key.
    with_flag = [
        command
        for command in commands(acceptance.COMPOSE, acceptance.LIVE_COMPOSE)
        if "--stdin-key" in command
    ]
    assert with_flag == [
        ["python", "scripts/stage1_acceptance_runtime.py", "acquire", "--stdin-key"]
    ]
    live = yaml.safe_load(acceptance.LIVE_COMPOSE.read_text())["services"]["live-acquire"]
    assert live["extends"]["service"] == "acquire"
    assert live["environment"] == {"FLOATCHAT_LIVE_INGESTION_ENABLED": "true"}


def complete_report():
    return {
        "closed": True,
        "state": "complete",
        "coverage": {
            "proved_complete": True,
            "gaps": [],
            "requested": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
        },
        "full_snapshot_balanced": True,
        "run_eligible_balanced": True,
        "scientific_level_delta_balanced": True,
        "reference_time_utc": "2025-04-01 00:00:00+00:00",
        "chunks": [{"leaf": True, "state": "complete"}],
        "scientific_no_change": True,
        "active_partition_no_change": True,
        "contract": "stage1-v3",
        "source_policy": {
            "policy": "S1-SOURCE-2",
            "source_exclusion_count": 0,
            "acceptance_qualification": "delivery_qualified_no_source_exclusions",
            "scientific_source_complete": "unknown",
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "quarantine",
        "reconciliation",
        "science",
        "generations",
        "contract",
        "source_complete",
        "unlabelled_exclusion",
    ],
)
def test_acceptance_cannot_pass_partial_coverage_quarantine_or_replay_change(change):
    report = copy.deepcopy(complete_report())
    if change == "gap":
        report["coverage"]["gaps"] = ["missing_coverage"]
    elif change == "quarantine":
        report["chunks"][0]["state"] = "quarantined"
    elif change == "reconciliation":
        report["run_eligible_balanced"] = False
    elif change == "science":
        report["scientific_no_change"] = False
    elif change == "contract":
        report["contract"] = "stage1-v2"
    elif change == "source_complete":
        report["source_policy"]["scientific_source_complete"] = True
    elif change == "unlabelled_exclusion":
        report["source_policy"]["source_exclusion_count"] = 1
    else:
        report["active_partition_no_change"] = False
    with pytest.raises(AssertionError):
        acceptance.validate_report(report, replay=True)


def test_complete_persisted_report_is_only_run_evidence_not_full_gate():
    acceptance.validate_report(complete_report(), replay=True)


@pytest.mark.parametrize("incomplete", [False, True, "interrupt", "worker_exit"])
def test_owner_orchestration_stdin_only_key_replay_isolation_and_failure_cleanup(
    monkeypatch, tmp_path, incomplete
):
    # Synthetic credential only; this test never discovers an owner credential.
    monkeypatch.setenv("ARGOVIS_API_KEY", "synthetic-owner-test-sentinel")
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    directory = tmp_path / "session"
    directory.mkdir()
    env_file = directory / "environment.env"
    env_file.write_text("LOCAL_TEST=true\n")
    env_file.chmod(0o600)
    manifest = {
        "session": "0123456789abcdef",
        "project": "isolated-test",
        "source_sha256": "synthetic-source-digest",
        "live_request_id": "live-request",
        "replay_request_id": "replay-request",
        "environment_file_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "preparation.json").write_text(json.dumps({"services_stopped": True}))
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(acceptance, "session_directory", lambda value: directory)
    monkeypatch.setattr(acceptance, "source_hash", lambda: "synthetic-source-digest")
    events = []

    class Input:
        def write(self, value):
            assert value == "synthetic-owner-test-sentinel\n"
            events.append("stdin_key")

        def close(self):
            events.append("stdin_closed")

    class Process:
        stdin = Input()

        def poll(self):
            return 5 if incomplete == "worker_exit" else None

        def wait(self, **kwargs):
            return 0

    class Sampler:
        def __init__(self, arguments):
            self.output = Path(arguments[arguments.index("--output") + 1])
            self.stop = Path(arguments[arguments.index("--stop-file") + 1])

        def wait(self, **kwargs):
            # It is told to stop (stop file) before it is waited for, then leaves its report.
            assert self.stop.exists()
            self.output.write_text(
                json.dumps({"pass": True, "samples": 7, "by_service": {"process": {"oom": 0}}})
            )
            return 0

    def popen(arguments, **kwargs):
        assert "synthetic-owner-test-sentinel" not in str(arguments) + str(kwargs["env"])
        assert "ARGOVIS_API_KEY" not in kwargs["env"]
        if "stage1_memory_sampler.py" in str(arguments):
            assert arguments[arguments.index("--project") + 1] == "isolated-test"
            events.append("memory_sampler")
            return Sampler(arguments)
        # The one container that holds the key is the live acquire process, nothing else.
        assert arguments[-1] == "live-acquire" and arguments.count("run") == 1
        events.append("live_worker")
        return Process()

    monkeypatch.setattr(acceptance.subprocess, "Popen", popen)

    def command(arguments, **kwargs):
        assert "synthetic-owner-test-sentinel" not in str(arguments)
        events.append("stop_upstream_worker")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(acceptance, "command", command)

    def compose(identifier, *args, **kwargs):
        if "ingest" in args:
            if incomplete == "worker_exit":
                kwargs["progress_callback"]()
            if incomplete == "interrupt":
                raise KeyboardInterrupt
            phase = "replay" if "--replay-run" in args else "live"
            events.append(phase + "_ingest")
            return SimpleNamespace(
                stdout=json.dumps({"run_id": phase + "-run"}), returncode=3 if incomplete else 0
            )
        if "report" in args:
            return SimpleNamespace(stdout=json.dumps(complete_report()), returncode=0)
        assert "live-acquire" not in args
        if "acquire" in args and "up" in args:
            events.append("internal_acquire")
        if "process" in args and "up" in args:
            events.append("process_pool")
        if "supervisor" in args and "up" in args:
            events.append("supervisor")
        if "stop" in args:
            events.append("cleanup")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(acceptance, "compose", compose)
    if incomplete == "worker_exit":
        with pytest.raises(acceptance.PreparationFailure, match="acceptance_live_worker_exited"):
            acceptance.execute("0123456789abcdef", True)
        assert not (tmp_path / "reports/stage1-acceptance-owner-result.json").exists()
    elif incomplete == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            acceptance.execute("0123456789abcdef", True)
        assert not (tmp_path / "reports/stage1-acceptance-owner-result.json").exists()
    elif incomplete:
        with pytest.raises(acceptance.PreparationFailure, match="acceptance_run_incomplete"):
            acceptance.execute("0123456789abcdef", True)
        assert "replay_ingest" not in events
        assert not (tmp_path / "reports/stage1-acceptance-owner-result.json").exists()
    else:
        acceptance.execute("0123456789abcdef", True)
        assert events.index("stop_upstream_worker") < events.index("internal_acquire")
        assert events.index("internal_acquire") < events.index("replay_ingest")
        # Live phase: key to the live acquire first, then the pool and supervisor; replay
        # restarts the same two worker containers (acquire without the key, and process).
        assert events.index("live_worker") < events.index("process_pool")
        assert events.index("process_pool") < events.index("live_ingest")
        assert events.count("internal_acquire") == 1 and events.count("process_pool") == 2
        result = json.loads((tmp_path / "reports/stage1-acceptance-owner-result.json").read_text())
        assert result["live_and_replay_runs_complete"] is True
        assert result["memory_evidence"]["pass"] is True
        assert result["memory_evidence"]["by_service"] == {"process": {"oom": 0}}
        assert result["worker_topology"] is None  # this synthetic manifest carries none
    assert "cleanup" in events
    assert "stdin_key" in events and "stdin_closed" in events
    cleanup = json.loads((directory / "last-cleanup.json").read_text())
    assert cleanup["data_preserved"] and cleanup["run_not_automatically_cancelled"]
    assert cleanup["failures"] == []
    # Per-container memory figures reach the evidence: the owner result on success, the
    # cleanup record when the run ended early, and always the full sampler report.
    assert events.index("process_pool") < events.index("memory_sampler")
    if "live_ingest" in events:  # the interrupted and exited-worker runs never get this far
        assert events.index("memory_sampler") < events.index("live_ingest")
    assert json.loads((tmp_path / "reports/stage1-acceptance-memory.json").read_text())["pass"]
    if incomplete:
        assert (
            cleanup["memory_evidence"]["available"] and cleanup["memory_evidence"]["samples"] == 7
        )
    else:
        assert cleanup["memory_evidence"] is None


def test_sampler_stop_is_best_effort_and_never_blocks_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    (tmp_path / "reports").mkdir()
    assert acceptance.stop_sampler(tmp_path, None) is None

    class Stuck:
        terminated = False

        def wait(self, timeout):
            if not self.terminated:
                raise acceptance.subprocess.TimeoutExpired("sampler", timeout)

        def terminate(self):
            self.terminated = True

    stuck = Stuck()
    # No report was written (or it is unreadable): unavailable, and the process is terminated.
    assert acceptance.stop_sampler(tmp_path, stuck) == {"available": False}
    assert stuck.terminated and (tmp_path / "memory.stop").exists()
    (tmp_path / "memory.json").write_text("{")
    assert acceptance.stop_sampler(tmp_path, Stuck()) == {"available": False}
    assert not (tmp_path / "reports/stage1-acceptance-memory.json").exists()


def test_sampler_start_clears_stale_state_and_survives_launch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    (tmp_path / "memory.stop").touch()
    (tmp_path / "memory.json").write_text("{}")
    started = []

    def popen(arguments, **kwargs):
        started.append((arguments, kwargs))
        raise OSError

    monkeypatch.setattr(acceptance.subprocess, "Popen", popen)
    assert acceptance.start_sampler(tmp_path, "project") is None
    assert not (tmp_path / "memory.stop").exists() and not (tmp_path / "memory.json").exists()
    ((arguments, kwargs),) = started
    assert arguments[1] == str(tmp_path / "scripts/stage1_memory_sampler.py")
    assert kwargs["env"] == acceptance.safe_environment() and "ARGOVIS_API_KEY" not in kwargs["env"]


def test_cleanup_ignores_repeated_ctrl_c_and_restores_handler(monkeypatch):
    previous = signal.getsignal(signal.SIGINT)
    observed = []

    def command(arguments, **kwargs):
        observed.append(signal.getsignal(signal.SIGINT))
        # A second Ctrl+C is ignored while cleanup is in progress.
        signal.raise_signal(signal.SIGINT)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(acceptance, "command", command)
    monkeypatch.setattr(acceptance, "compose", lambda *args, **kwargs: None)
    assert acceptance.stop_acceptance("0123456789abcdef", "isolated-test") == []
    assert observed and all(handler == signal.SIG_IGN for handler in observed)
    assert signal.getsignal(signal.SIGINT) == previous


def test_progress_never_prints_unexpected_fields_or_unsafe_states(monkeypatch, capsys):
    payload = {
        "state": "validating",
        "leaf_states": {"complete": 120, "failed": 44, "quarantined": 8, "planned": 1088},
        "unexpected_secret": "synthetic-secret-sentinel",
        "unexpected_url": "https://unexpected.invalid",
    }
    monkeypatch.setattr(
        acceptance, "compose", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload))
    )
    acceptance.print_progress("0123456789abcdef", "request", "live")
    output = capsys.readouterr().out
    assert "chunks=1260 complete=120 failed=44 quarantined=8" in output
    assert "sentinel" not in output and "http" not in output
    payload["state"] = "synthetic-secret-sentinel"
    acceptance.print_progress("0123456789abcdef", "request", "live")
    output = capsys.readouterr().out
    assert "progress_temporarily_unavailable" in output and "sentinel" not in output


def test_progress_shows_queue_depth_by_ticket_kind_and_nothing_else(monkeypatch, capsys):
    payload = {
        "state": "fetching",
        "leaf_states": {"fetching": 4, "planned": 12},
        "tickets": {"acquire": {"queued": 3, "started": 4}, "process": {"queued": 1, "started": 0}},
    }
    monkeypatch.setattr(
        acceptance, "compose", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload))
    )
    acceptance.print_progress("0123456789abcdef", "request", "live")
    assert "chunks=16 complete=0 failed=0 quarantined=0 acquire_queued=3 process_queued=1" in (
        capsys.readouterr().out
    )
    for bad in (
        {"unexpected": {"queued": 1, "started": 1}},
        {"acquire": {"queued": 1, "started": 1, "token": "synthetic-secret-sentinel"}},
        {"acquire": {"queued": -1, "started": 1}},
    ):
        payload["tickets"] = bad
        acceptance.print_progress("0123456789abcdef", "request", "live")
        output = capsys.readouterr().out
        assert "progress_temporarily_unavailable" in output and "sentinel" not in output


def test_long_command_polls_with_safe_callback_and_preserves_result():
    updates = []
    result = acceptance.command(
        [sys.executable, "-c", "import time; time.sleep(0.05); print('{}')"],
        progress_callback=lambda: updates.append("counter_update"),
        timeout=2,
    )
    assert updates and result.returncode == 0 and result.stdout == "{}\n"


def test_long_command_interrupt_reaps_client_process_and_never_succeeds(monkeypatch):
    original = acceptance.subprocess.Popen
    processes = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(acceptance.subprocess, "Popen", spawn)
    with pytest.raises(KeyboardInterrupt):
        acceptance.command(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            progress_callback=interrupt,
            timeout=2,
        )
    assert len(processes) == 1 and processes[0].poll() is not None


def make_cgroup(base, *, anon, peak, limit, oom=0, kills=0):
    base.mkdir(parents=True)
    (base / "memory.events").write_text(f"low 0\nhigh 0\nmax 0\noom {oom}\noom_kill {kills}\n")
    (base / "memory.stat").write_text(f"anon {anon}\nfile 1\n")
    (base / "memory.max").write_text(f"{limit}\n")
    (base / "memory.peak").write_text(f"{peak}\n")


def test_sampler_selects_every_worker_container_and_no_other_service(monkeypatch):
    output = (
        "a1 acquire proj-acquire-1\nb2 process proj-process-1\nc3 supervisor proj-supervisor-1\n"
        "d4 live-acquire proj-live-owner\ne5 db proj-db-1\nbroken line\n"
    )
    monkeypatch.setattr(
        sampler.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output)
    )
    assert sampler.containers("proj") == {
        "a1": ("acquire", "proj-acquire-1"),
        "b2": ("process", "proj-process-1"),
        "d4": ("live-acquire", "proj-live-owner"),
    }


def test_sampler_survives_a_docker_listing_timeout(monkeypatch, tmp_path):
    def stalled(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 20)

    monkeypatch.setattr(sampler.subprocess, "run", stalled)
    assert sampler.containers("proj") is None
    gib = 1024**3
    make_cgroup(tmp_path / "cg/a1", anon=gib // 4, peak=gib // 2, limit=gib)
    make_cgroup(tmp_path / "cg/b2", anon=gib // 4, peak=gib // 2, limit=2 * gib)
    monkeypatch.setattr(sampler, "CGROUP", tmp_path / "cg")
    listings = iter(
        [{"a1": ("live-acquire", "proj-live-owner"), "b2": ("process", "proj-process-1")}, None]
    )
    monkeypatch.setattr(sampler, "containers", lambda project: next(listings))
    stop = tmp_path / "stop"
    polls = []
    monkeypatch.setattr(
        sampler.time, "sleep", lambda _: polls.append(1) if not polls else stop.write_text("")
    )
    output = tmp_path / "memory.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["sampler", "--project", "proj", "--output", str(output), "--stop-file", str(stop)],
    )
    assert sampler.main() == 0
    report = json.loads(output.read_text())
    assert report["missed_container_listings"] == 1 and report["samples"] == 4
    assert report["pass"] is True


@pytest.mark.parametrize("process_limit", [2 * 1024**3, 4 * 1024**3])
def test_sampler_reports_per_container_peaks_and_passes_within_limits(
    monkeypatch, tmp_path, process_limit
):
    gib = 1024**3
    make_cgroup(tmp_path / "cg/a1", anon=gib // 2, peak=gib, limit=gib)
    make_cgroup(tmp_path / "cg/b2", anon=gib + gib // 2, peak=2 * gib - 1, limit=process_limit)
    monkeypatch.setattr(sampler, "CGROUP", tmp_path / "cg")
    monkeypatch.setattr(
        sampler,
        "containers",
        lambda project: {"a1": ("acquire", "proj-acquire-1"), "b2": ("process", "proj-process-1")},
    )
    stop = tmp_path / "stop"
    monkeypatch.setattr(sampler.time, "sleep", lambda _: stop.write_text(""))
    output = tmp_path / "memory.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["sampler", "--project", "proj", "--output", str(output), "--stop-file", str(stop)],
    )
    assert sampler.main() == 0
    report = json.loads(output.read_text())
    assert report["pass"] is True and report["samples"] == 2
    assert {worker["service"] for worker in report["workers"]} == {"acquire", "process"}
    process = report["by_service"]["process"]
    assert process["anon_peak_bytes"] == gib + gib // 2 and process["memory_max"] == process_limit
    assert report["by_service"]["acquire"]["oom_kill"] == 0


@pytest.mark.parametrize(
    "change", ["oom", "acquire_limit", "anon_over_limit", "no_process", "no_acquire"]
)
def test_sampler_fails_oom_wrong_limit_overshoot_and_missing_halves(monkeypatch, tmp_path, change):
    gib = 1024**3
    acquire = dict(anon=gib // 2, peak=gib, limit=2 * gib if change == "acquire_limit" else gib)
    process = dict(anon=2 * gib if change == "anon_over_limit" else gib, peak=gib, limit=2 * gib)
    if change == "oom":
        process.update(oom=1, kills=1)
    make_cgroup(tmp_path / "cg/a1", **acquire)
    make_cgroup(tmp_path / "cg/b2", **process)
    monkeypatch.setattr(sampler, "CGROUP", tmp_path / "cg")
    found = {"a1": ("live-acquire", "proj-live-owner"), "b2": ("process", "proj-process-1")}
    if change == "no_process":
        del found["b2"]
    if change == "no_acquire":
        del found["a1"]
    monkeypatch.setattr(sampler, "containers", lambda project: found)
    stop = tmp_path / "stop"
    monkeypatch.setattr(sampler.time, "sleep", lambda _: stop.write_text(""))
    output = tmp_path / "memory.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["sampler", "--project", "proj", "--output", str(output), "--stop-file", str(stop)],
    )
    assert sampler.main() == 0
    assert json.loads(output.read_text())["pass"] is False
