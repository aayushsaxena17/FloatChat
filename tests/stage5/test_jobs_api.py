"""The job endpoints over a memory store: creation, attachment, scoping, SSE, cancel, download."""

import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from floatchat_api.jobs_api import JobsRuntime, event_stream
from floatchat_api.main import create_app
from floatchat_core.jobs.artefacts import sign, verify
from floatchat_core.jobs.model import JobLimits
from floatchat_core.jobs.store import MemoryJobStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2"))
from test_api import FakeService  # noqa: E402  (the Stage 2 query-service double)

KEY = "k" * 32
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
HEADERS = {"X-FloatChat-Client": "browser-1"}
REQUEST: dict[str, Any] = {
    "time_range": {"start": "2015-04-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "depth_dbar": {"min": 0, "max": 2000},
    "format": "parquet",
}


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False

    def iter_chunks(self, size: int):
        for start in range(0, len(self.payload), size):
            yield self.payload[start : start + size]

    def close(self) -> None:
        self.closed = True


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": FakeBody(self.objects[Key])}


@pytest.fixture
def store() -> MemoryJobStore:
    return MemoryJobStore(clock=lambda: NOW)


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(store: MemoryJobStore, storage: FakeStorage) -> TestClient:
    runtime = JobsRuntime(
        store=store,
        limits=JobLimits(),
        signing_key=KEY,
        storage_factory=lambda settings: storage,
        clock=lambda: NOW,
    )
    runtime._settings = type(  # type: ignore[assignment]
        "S", (), {"object_storage_bucket": "floatchat-dev", "artefact_signing_key": None}
    )()
    return TestClient(
        create_app(query_service=FakeService(), jobs_runtime=runtime), raise_server_exceptions=False
    )


def test_create_lists_and_reads_a_job_scoped_to_the_client(client: TestClient) -> None:
    created = client.post("/v1/exports", json=REQUEST, headers=HEADERS)
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["created"] is True and body["attached"] is False
    job = body["job"]
    assert job["state"] == "queued" and job["request"]["format"] == "parquet"
    assert job["plan"]["plan_schema"] == "stage2-plan-v1"
    assert job["request"]["schema"] == "export-request-v1"
    listed = client.get("/v1/jobs", headers=HEADERS).json()["jobs"]
    assert [row["id"] for row in listed] == [job["id"]]
    detail = client.get(f"/v1/jobs/{job['id']}", headers=HEADERS).json()
    assert detail["job"]["id"] == job["id"] and detail["chunks"] == [] and detail["artefacts"] == []
    # Another client sees neither the list entry nor the detail.
    other = {"X-FloatChat-Client": "browser-2"}
    assert client.get("/v1/jobs", headers=other).json()["jobs"] == []
    missing = client.get(f"/v1/jobs/{job['id']}", headers=other)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "job_not_found"
    assert client.get("/v1/jobs").json()["error"]["code"] == "client_required"


def test_identical_request_attaches_and_the_idempotency_key_is_honoured(client: TestClient) -> None:
    first = client.post("/v1/exports", json=REQUEST, headers={**HEADERS, "Idempotency-Key": "a1"})
    again = client.post("/v1/exports", json=REQUEST, headers={**HEADERS, "Idempotency-Key": "a1"})
    assert again.status_code == 202 and again.json()["created"] is False
    assert again.json()["job"]["id"] == first.json()["job"]["id"]
    attached = client.post(
        "/v1/exports", json={**REQUEST, "idempotency_key": "b2"}, headers=HEADERS
    )
    assert attached.json()["attached"] is True
    assert attached.json()["job"]["id"] == first.json()["job"]["id"]
    different = client.post("/v1/exports", json={**REQUEST, "format": "csv"}, headers=HEADERS)
    assert different.json()["created"] is True
    assert different.json()["job"]["id"] != first.json()["job"]["id"]


def test_invalid_requests_are_rejected_with_details(client: TestClient) -> None:
    unknown = client.post(
        "/v1/exports",
        json={**REQUEST, "geography": {"kind": "named_region", "value": "Atlantis"}},
        headers=HEADERS,
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_region"
    too_long = client.post(
        "/v1/exports",
        json={
            **REQUEST,
            "time_range": {"start": "1990-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
        },
        headers=HEADERS,
    )
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["error"]["details"][0]["code"] == "unbounded_request", too_long.text
    bad = client.post("/v1/exports", json={**REQUEST, "format": "netcdf"}, headers=HEADERS)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_parameter"


def test_cancel_uses_the_version_and_conflicts_when_finished(
    client: TestClient, store: MemoryJobStore
) -> None:
    job = client.post("/v1/exports", json=REQUEST, headers=HEADERS).json()["job"]
    stale = client.post(f"/v1/jobs/{job['id']}/cancel", json={"version": 99}, headers=HEADERS)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "job_conflict"
    cancelled = client.post(
        f"/v1/jobs/{job['id']}/cancel", json={"version": job["version"]}, headers=HEADERS
    )
    assert cancelled.status_code == 200 and cancelled.json()["job"]["state"] == "cancelled"
    again = client.post(f"/v1/jobs/{job['id']}/cancel", headers=HEADERS)
    assert again.status_code == 409
    assert client.post(f"/v1/jobs/{uuid.uuid4()}/cancel", headers=HEADERS).status_code == 404


def test_events_stream_replays_resumes_and_ends_with_the_terminal_event(
    client: TestClient, store: MemoryJobStore
) -> None:
    job = client.post("/v1/exports", json=REQUEST, headers=HEADERS).json()["job"]
    store.emit(job["id"], "planned", {"slots_total": 10})
    store.emit(job["id"], "chunk", {"seq": 1, "state": "running"})
    store.update(job["id"], state="completed", finished=True)
    store.emit(job["id"], "finished", {"state": "completed"})
    with client.stream("GET", f"/v1/jobs/{job['id']}/events", headers=HEADERS) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    blocks = [block for block in text.split("\n\n") if block.strip()]
    ids = [line for block in blocks for line in block.splitlines() if line.startswith("id: ")]
    kinds = [
        line.split(": ", 1)[1]
        for block in blocks
        for line in block.splitlines()
        if line.startswith("event: ")
    ]
    assert ids == ["id: 1", "id: 2", "id: 3"] and kinds == ["planned", "chunk", "finished"]
    assert '"job_state": "completed"' in blocks[-1]
    with client.stream(
        "GET", f"/v1/jobs/{job['id']}/events", headers={**HEADERS, "Last-Event-ID": "2"}
    ) as response:
        resumed = "".join(response.iter_text())
    assert resumed.count("event: ") == 1 and "event: finished" in resumed
    # A stream over a quiet job sends keep-alive comments and closes once the job finishes.
    quiet = client.post("/v1/exports", json={**REQUEST, "format": "csv"}, headers=HEADERS).json()[
        "job"
    ]
    ticks = {"n": 0}

    def sleep(seconds: float) -> None:
        ticks["n"] += 1
        if ticks["n"] == 2:
            store.update(quiet["id"], state="failed", finished=True)

    out = list(event_stream(store, quiet["id"], 0, poll=0, heartbeat=0, sleep=sleep))
    assert (
        out[0].startswith(": keep-alive") and out[-1].startswith("id: ") and "finished" in out[-1]
    )


def test_download_needs_a_valid_token_and_streams_the_object(
    client: TestClient, store: MemoryJobStore, storage: FakeStorage
) -> None:
    job = client.post("/v1/exports", json=REQUEST, headers=HEADERS).json()["job"]
    key = f"exports/{job['id']}/floatchat-export-{job['id'][:8]}.parquet"
    artefact = store.add_artefact(
        job_id=job["id"],
        format="parquet",
        role="data",
        object_key=key,
        bytes=5,
        sha256="c" * 64,
        row_count=3,
        profile_count=1,
        manifest={"schema": "export-manifest-v1"},
        expires_at=NOW + timedelta(days=7),
    )
    storage.objects[key] = b"hello"
    detail = client.get(f"/v1/jobs/{job['id']}", headers=HEADERS).json()
    url = detail["artefacts"][0]["download_url"]
    assert url is not None and url.startswith(f"/v1/artefacts/{artefact.id}/download?token=")
    downloaded = client.get(url)
    assert downloaded.status_code == 200 and downloaded.content == b"hello"
    assert downloaded.headers["content-disposition"].endswith('.parquet"')
    assert downloaded.headers["x-content-sha256"] == "c" * 64
    forged = client.get(f"/v1/artefacts/{artefact.id}/download?token=1.{'0' * 64}")
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "token_invalid"
    assert client.get(f"/v1/artefacts/{artefact.id}/download").status_code == 403
    expired = sign(KEY, artefact.id, NOW - timedelta(seconds=1))
    assert client.get(f"/v1/artefacts/{artefact.id}/download?token={expired}").status_code == 403
    assert verify(KEY, artefact.id, sign(KEY, artefact.id, NOW + timedelta(minutes=1)), NOW)
    assert not verify(
        KEY, str(uuid.uuid4()), sign(KEY, artefact.id, NOW + timedelta(minutes=1)), NOW
    )
    # An expired artefact is gone even with a good token (state before object, ADR-0079).
    store.expire_artefacts(NOW + timedelta(days=8))
    good = sign(KEY, artefact.id, NOW + timedelta(minutes=1))
    gone = client.get(f"/v1/artefacts/{artefact.id}/download?token={good}")
    assert gone.status_code == 410 and gone.json()["error"]["code"] == "artefact_unavailable"
    assert (
        client.get(f"/v1/jobs/{job['id']}", headers=HEADERS).json()["artefacts"][0]["download_url"]
        is None
    )
