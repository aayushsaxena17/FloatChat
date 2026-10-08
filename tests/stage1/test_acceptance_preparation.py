"""Offline guards for acceptance preparation; no upstream or credential access."""

import copy
import hashlib
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import stage1_acceptance as acceptance
from scripts import stage1_acceptance_runtime as runtime

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


def test_runtime_stdin_credential_refused_outside_live_worker(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["runtime", "proof", "--stdin-key"])
    with pytest.raises(runtime.Rejection, match="live_acceptance_opt_in_required"):
        runtime.main()


def test_compose_has_private_resources_no_ports_or_beat_and_separate_egress():
    configuration = yaml.safe_load(acceptance.COMPOSE.read_text())
    assert configuration["networks"] == {"default": {"internal": True}}
    assert set(configuration["volumes"]) == {"postgres_data", "redis_data", "minio_data"}
    assert not any(value.get("external") for value in configuration["volumes"].values())
    for name, service in configuration["services"].items():
        assert "ports" not in service and "ARGOVIS_API_KEY" not in str(service)
        assert "beat" not in name and service["pull_policy"] == "never"
    worker = configuration["services"]["worker"]
    assert worker["mem_limit"] == "1g"
    assert worker["environment"]["FLOATCHAT_LIVE_INGESTION_ENABLED"] == "false"
    assert worker["environment"]["INGESTION_REDIS_URL"].endswith("/13")
    assert "ACCEPTANCE_REDIS_PREFIX" in worker["environment"]
    live = yaml.safe_load(acceptance.LIVE_COMPOSE.read_text())
    assert live["services"]["live-worker"]["networks"] == ["default", "upstream"]
    assert live["services"]["live-worker"]["profiles"] == ["live"]
    assert "ARGOVIS_API_KEY" not in str(live)


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

    def popen(arguments, **kwargs):
        assert "synthetic-owner-test-sentinel" not in str(arguments) + str(kwargs["env"])
        assert "ARGOVIS_API_KEY" not in kwargs["env"]
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
        if "worker" in args and "up" in args:
            events.append("internal_worker")
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
        assert events.index("stop_upstream_worker") < events.index("internal_worker")
        assert events.index("internal_worker") < events.index("replay_ingest")
    assert "cleanup" in events
    assert "stdin_key" in events and "stdin_closed" in events
    cleanup = json.loads((directory / "last-cleanup.json").read_text())
    assert cleanup["data_preserved"] and cleanup["run_not_automatically_cancelled"]
    assert cleanup["failures"] == []


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
