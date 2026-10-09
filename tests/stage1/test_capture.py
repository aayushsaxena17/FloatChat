"""Recorder controls with synthetic responses; no live-capture attribution."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion.argovis import SOURCE_CONTRACT, TRANSLATOR_SHA256
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.transport import HTTPFailure, Response

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_recorder", ROOT / "scripts/capture_stage1_fixtures.py"
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
    # Never inspect an inherited real environment. Replace the recorder's env
    # interface with this entirely synthetic sentinel mapping.
    monkeypatch.setattr(
        module, "os", SimpleNamespace(environ={"ARGOVIS_API_KEY": "synthetic-recorder-sentinel"})
    )
    return module


def test_F01_B05_recorder_opt_in_precedes_credential_access(recorder):
    class Env:
        def get(self, name):
            pytest.fail("Credential access without opt-in")

    recorder.os.environ = Env()
    with pytest.raises(Rejection, match="live_capture_opt_in_required"):
        recorder.capture(["example"], opted_in=False)


@pytest.mark.parametrize("supplemented", [False, True])
def test_F01_B05_S03_recorder_sanitizes_and_scans_before_fixture_copy(
    recorder, wire, linked_metadata, monkeypatch, supplemented
):
    if supplemented:
        wire["data_info"][0] += ["chla_fluorescence", "chla_fluorescence_qc"]
        wire["data_info"][2] += [["ru", "A"], [None, None]]
        wire["data"] += [[1, None, 3], [1, 2, "unknown"]]
    calls = []

    def fetch(path, parameters, credential, account, **kwargs):
        assert credential == "synthetic-recorder-sentinel"
        assert kwargs["raw_limit"] == 1024**2 and kwargs["json_limit"] == 8 * 1024**2
        assert path in ("/argo", "/argo/meta")
        calls.append((path, parameters))
        row = linked_metadata[parameters["id"]] if path == "/argo/meta" else wire
        data = json.dumps([{**row, "api_key": credential}]).encode()
        account(len(data))
        return Response(data, len(data), datetime.now(UTC), {})

    monkeypatch.setattr(recorder, "fetch", fetch)
    monkeypatch.setattr(
        recorder.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 + "\n" if kwargs.get("text") else b"",
    )
    scanned = []

    def scan(command, **kwargs):
        assert "--redact=100" in command and "--max-decode-depth=3" in command
        directory = Path(command[2])
        assert not (recorder.ROOT / "tests/fixtures/argovis/recorded").exists()
        assert all(
            b"synthetic-recorder-sentinel" not in file.read_bytes() for file in directory.iterdir()
        )
        scanned.append(directory)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(recorder.subprocess, "run", scan)
    bundle = recorder.capture([wire["_id"]], opted_in=True)
    assert len(calls) == 4 and len(scanned) == 1
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["scope"] == "small_profile_id_capture_not_region_ingestion"
    assert manifest["expected_profiles"][0]["levels"] == 3
    assert manifest["versions"]["source_contract"] == SOURCE_CONTRACT
    assert manifest["versions"]["translator_sha256"] == TRANSLATOR_SHA256
    if supplemented:
        recorded = json.loads((bundle / "02-profile.json").read_text())[0]
        assert recorded["data_info"] == wire["data_info"]
        assert recorded["data"][-2:] == wire["data"][-2:]
    originals = scanned[0].parent / "originals"
    assert originals.stat().st_mode & 0o777 == 0o700
    assert all(file.stat().st_mode & 0o777 == 0o600 for file in originals.iterdir())
    assert any(b"synthetic-recorder-sentinel" in file.read_bytes() for file in originals.iterdir())


def test_F01_rejected_scan_never_copies_fixture(recorder, wire, linked_metadata, monkeypatch):
    def fetch(path, parameters, credential, account, **kwargs):
        row = linked_metadata[parameters["id"]] if path == "/argo/meta" else wire
        data = json.dumps([row]).encode()
        account(len(data))
        return Response(data, len(data), datetime.now(UTC), {})

    monkeypatch.setattr(recorder, "fetch", fetch)
    monkeypatch.setattr(
        recorder.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 + "\n" if kwargs.get("text") else b"",
    )
    monkeypatch.setattr(
        recorder.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(Rejection, match="sanitized_capture_secret_scan_failed"):
        recorder.capture([wire["_id"]], opted_in=True)
    assert not (recorder.ROOT / "tests/fixtures/argovis/recorded").exists()


@pytest.mark.parametrize(
    "failed_role", ["inventory_before", "profile", "inventory_after", "metadata"]
)
@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_B05_capture_http_diagnostic_allowlist_no_retry(
    recorder, wire, linked_metadata, monkeypatch, capsys, failed_role, status
):
    roles = ["inventory_before", "profile", "inventory_after", "metadata"]
    calls = []

    class PoisonedFailure(HTTPFailure):
        def __str__(self):
            pytest.fail("HTTP failure must never be rendered")

        def __repr__(self):
            pytest.fail("HTTP failure must never be represented")

    def fetch(path, parameters, credential, account, **kwargs):
        role = roles[len(calls)]
        calls.append(role)
        if role == failed_role:
            failure = PoisonedFailure(status, "27")
            failure.headers = {
                "Authorization": credential,
                "Location": "https://unexpected.invalid/?key=" + credential,
            }
            failure.body = b"response body containing credential"
            failure.args = (credential, failure.headers, failure.body)
            raise failure
        row = linked_metadata[parameters["id"]] if path == "/argo/meta" else wire
        data = json.dumps([row]).encode()
        return Response(data, len(data), datetime.now(UTC), {})

    monkeypatch.setattr(recorder, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["capture", "--live-opt-in", "--profile-id", wire["_id"]])
    assert recorder.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    expected = {
        "category": "upstream_http_status",
        "http_status": status,
        "selected_profile_id": wire["_id"],
        "request_role": failed_role,
    }
    if status == 429:
        expected["retry_after_seconds"] = 27.0
    assert json.loads(output.out) == expected
    assert calls == roles[: roles.index(failed_role) + 1]
    assert not (recorder.ROOT / "tests/fixtures/argovis/recorded").exists()


@pytest.mark.parametrize(
    "header",
    [
        "301",
        "-1",
        "9" * 129,
        "NaN",
        "Authorization: synthetic-recorder-sentinel",
        "https://unexpected.invalid/?key=synthetic-recorder-sentinel",
    ],
)
def test_B05_capture_invalid_retry_after_is_omitted(recorder, monkeypatch, capsys, header):
    def fetch(*args, **kwargs):
        raise HTTPFailure(429, header)

    monkeypatch.setattr(recorder, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["capture", "--live-opt-in", "--profile-id", "13857_068"])
    assert recorder.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "category": "upstream_http_status",
        "http_status": 429,
        "selected_profile_id": "13857_068",
        "request_role": "inventory_before",
    }


def test_B05_capture_other_exception_stays_generic(recorder, monkeypatch, capsys):
    def fetch(*args, **kwargs):
        raise RuntimeError(
            "synthetic-recorder-sentinel https://unexpected.invalid/?credential=hidden"
        )

    monkeypatch.setattr(recorder, "fetch", fetch)
    monkeypatch.setattr(sys, "argv", ["capture", "--live-opt-in", "--profile-id", "13857_068"])
    assert recorder.main() == 5
    output = capsys.readouterr()
    assert output.out == "capture_failed_no_sensitive_diagnostics\n" and output.err == ""
