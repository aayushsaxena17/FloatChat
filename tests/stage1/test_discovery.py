"""Synthetic discovery controls; never live calls or recorded F01 representations."""

import hashlib
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion.numeric import MIB, Rejection
from floatchat_core.ingestion.transport import HTTPFailure, Response

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_discovery_recorder", ROOT / "scripts/discover_stage1_fixture_ids.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = tmp_path / "fresh"
    (fake / ".cache/tools").mkdir(parents=True)
    (fake / ".cache/tools/gitleaks").write_text("synthetic scanner placeholder")
    (fake / "docs/upstream").mkdir(parents=True)
    (fake / "docs/upstream/argovis-2.36.2.json").write_bytes(
        (ROOT / "docs/upstream/argovis-2.36.2.json").read_bytes()
    )
    monkeypatch.setattr(module, "ROOT", fake)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "private-home"))
    monkeypatch.setattr(
        module, "os", SimpleNamespace(environ={"ARGOVIS_API_KEY": "synthetic-discovery-sentinel"})
    )
    return module


def test_F01_B05_discovery_opt_in_precedes_credential_access(discovery):
    class Env:
        def get(self, name):
            pytest.fail("No credential access without explicit opt-in")

    discovery.os.environ = Env()
    with pytest.raises(Rejection, match="live_capture_opt_in_required"):
        discovery.discover(opted_in=False)


@pytest.mark.parametrize("count", [0, 1, 20])
def test_F01_B05_discovery_one_documented_request_scan_before_copy(discovery, monkeypatch, count):
    calls = []
    scanned = []

    def fetch(path, parameters, credential, account, **kwargs):
        calls.append((path, parameters))
        assert path == "/argo"
        assert parameters == {
            "startDate": "2026-09-28T00:00:00Z",
            "endDate": "2026-10-05T00:00:00Z",
            "polygon": "[[65,-5],[70,-5],[70,0],[65,0],[65,-5]]",
        }
        assert "data" not in parameters and "limit" not in parameters
        assert kwargs["raw_limit"] == MIB and kwargs["json_limit"] == 8 * MIB
        assert 0 < kwargs["deadline"] - time.monotonic() <= 120
        assert credential == "synthetic-discovery-sentinel"
        payload = json.dumps(
            [{"_id": f"synthetic_{i}", "api_key": credential} for i in range(count)]
        ).encode()
        account(len(payload))
        return Response(payload, len(payload), datetime.now(UTC), {"Authorization": credential})

    def scan(command, **kwargs):
        directory = Path(command[2])
        assert "--redact=100" in command and "--max-decode-depth=3" in command
        assert kwargs["timeout"] == 60
        assert not (discovery.ROOT / "tests/fixtures/argovis").exists()
        assert all(
            b"synthetic-discovery-sentinel" not in p.read_bytes() for p in directory.iterdir()
        )
        scanned.append(directory)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(discovery, "fetch", fetch)
    monkeypatch.setattr(discovery.subprocess, "run", scan)
    bundle = discovery.discover(opted_in=True)
    assert len(calls) == len(scanned) == 1
    assert bundle.parent.name == "discovery"
    assert not (discovery.ROOT / "tests/fixtures/argovis/recorded").exists()
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["candidate_count"] == count
    assert manifest["bounds"]["requests"] == 1
    assert manifest["bounds"]["automatic_retries"] == 0
    assert manifest["scope"] == "candidate_discovery_only_not_F01_or_regional_coverage"
    assert manifest["specification"]["release"] == "2.36.2"
    assert (
        manifest["response"]["sha256"]
        == hashlib.sha256((bundle / "01-inventory_discovery.json").read_bytes()).hexdigest()
    )
    original = scanned[0].parent / "originals"
    assert original.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in original.iterdir())


@pytest.mark.parametrize(
    "rows",
    [
        [{"_id": f"synthetic_{i}"} for i in range(21)],
        [{"_id": "duplicate"}, {"_id": "duplicate"}],
        [{"_id": "unexpected", "data": []}],
        [{"_id": "https://unexpected.invalid/?credential=hidden"}],
        {"_id": "not_array"},
    ],
)
def test_F01_B01_discovery_invalid_or_excess_inventory_never_copied(discovery, monkeypatch, rows):
    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        payload = json.dumps(rows).encode()
        return Response(payload, len(payload), datetime.now(UTC), {})

    monkeypatch.setattr(discovery, "fetch", fetch)
    with pytest.raises(Rejection):
        discovery.discover(opted_in=True)
    assert calls == [1]
    assert not (discovery.ROOT / "tests/fixtures/argovis").exists()


def test_F01_B05_discovery_scan_failure_never_copied(discovery, monkeypatch):
    monkeypatch.setattr(
        discovery, "fetch", lambda *args, **kwargs: Response(b"[]", 2, datetime.now(UTC), {})
    )
    monkeypatch.setattr(
        discovery.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(Rejection, match="sanitized_capture_secret_scan_failed"):
        discovery.discover(opted_in=True)
    assert not (discovery.ROOT / "tests/fixtures/argovis").exists()


@pytest.mark.parametrize("status", [404, 429, 503])
def test_B05_discovery_http_diagnostic_no_retry_or_sensitive_rendering(
    discovery, monkeypatch, capsys, status
):
    calls = []

    class PoisonedFailure(HTTPFailure):
        def __str__(self):
            pytest.fail("Never render an HTTP failure")

        def __repr__(self):
            pytest.fail("Never represent an HTTP failure")

    def fetch(*args, **kwargs):
        calls.append(1)
        failure = PoisonedFailure(status, "27")
        failure.headers = {"Authorization": "synthetic-discovery-sentinel"}
        failure.body = b"sensitive body"
        failure.args = ("https://unexpected.invalid/?credential=hidden", failure.headers)
        raise failure

    monkeypatch.setattr(discovery, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["discover", "--live-opt-in"])
    assert discovery.main() == 2
    output = capsys.readouterr()
    expected = {
        "category": "upstream_http_status",
        "http_status": status,
        "request_role": "inventory_discovery",
    }
    if status == 429:
        expected["retry_after_seconds"] = 27.0
    assert json.loads(output.out) == expected and output.err == ""
    assert calls == [1]


def test_B05_discovery_other_exception_stays_generic(discovery, monkeypatch, capsys):
    def fetch(*args, **kwargs):
        raise RuntimeError("synthetic-discovery-sentinel https://unexpected.invalid/")

    monkeypatch.setattr(discovery, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["discover", "--live-opt-in"])
    assert discovery.main() == 5
    output = capsys.readouterr()
    assert output.out == "capture_failed_no_sensitive_diagnostics\n" and output.err == ""


@pytest.mark.parametrize(
    "header",
    [
        "301",
        "-1",
        "9" * 129,
        "NaN",
        "Authorization: synthetic-discovery-sentinel",
        "https://unexpected.invalid/?key=synthetic-discovery-sentinel",
    ],
)
def test_B05_discovery_invalid_retry_after_omitted(discovery, monkeypatch, capsys, header):
    def fetch(*args, **kwargs):
        raise HTTPFailure(429, header)

    monkeypatch.setattr(discovery, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["discover", "--live-opt-in"])
    assert discovery.main() == 2
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "category": "upstream_http_status",
        "http_status": 429,
        "request_role": "inventory_discovery",
    }
    assert output.err == ""


def test_B01_discovery_compressed_total_rejected_before_copy(discovery, monkeypatch):
    def fetch(path, parameters, credential, account, **kwargs):
        account(MIB)
        account(1)
        pytest.fail("Excess received bytes must stop discovery")

    monkeypatch.setattr(discovery, "fetch", fetch)
    with pytest.raises(Rejection, match="small_discovery_total_size_limit"):
        discovery.discover(opted_in=True)
    assert not (discovery.ROOT / "tests/fixtures/argovis").exists()


def test_B05_discovery_missing_variable_name_only(discovery, monkeypatch, capsys):
    discovery.os.environ = {}
    monkeypatch.setattr(sys, "argv", ["discover", "--live-opt-in"])
    assert discovery.main() == 2
    output = capsys.readouterr()
    assert output.out == "ARGOVIS_API_KEY\n" and output.err == ""
