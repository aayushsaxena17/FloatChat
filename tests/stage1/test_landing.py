import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from floatchat_core.ingestion import transport as transport_module
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.transport import HTTPFailure, Response


class Store:
    def __init__(self):
        self.data = {}

    def write_temporary(self, key, payload, deadline):
        self.data[key] = payload

    def read(self, key, max_bytes, deadline):
        if key not in self.data:
            raise Rejection("object_missing")
        assert len(self.data[key]) <= max_bytes
        return self.data[key]

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])


class Repository:
    def __init__(self):
        self.count = 0
        self.bytes_received = 0
        self.finishes = []
        self.manifest = None
        self.locked = False

    def verified_landing(self, authority, key):
        return self.manifest

    def http_reserve(self, authority, key, role, parameters):
        assert self.locked
        if self.count >= 4:
            raise Rejection("http_retry_exhausted")
        self.count += 1
        return uuid.uuid4(), self.count

    def heartbeat(self, authority):
        pass

    def account_received(self, authority, attempt, count):
        self.bytes_received += count

    def finish_attempt(
        self, authority, attempt, disposition, status=None, error=None, manifest=None
    ):
        self.finishes.append((disposition, status, error))
        if manifest:
            self.manifest = {**manifest, "object_key": manifest["key"]}

    @contextmanager
    def upstream_slot(self, authority, deadline):
        assert not self.locked
        self.locked = True
        try:
            yield
        finally:
            self.locked = False


@pytest.fixture(autouse=True)
def private_originals(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))


@pytest.fixture(autouse=True)
def immediate_retries(monkeypatch):
    # Retry ownership/persistence tests; the backoff policy is pinned in test_wire.
    monkeypatch.setattr(transport_module, "RETRY_MAXIMA", {1: 0.0, 2: 0.0, 3: 0.0})


def owner(repository, store, transport, *, enabled=lambda: True):
    return RequestOwner(
        repository,
        store,
        Authority(uuid.uuid4(), uuid.uuid4(), 1, 1),
        deadline=time.monotonic() + 20,
        application_commit="offline-test",
        enabled=enabled,
        credential=lambda: "synthetic-test-sentinel",
        transport=transport,
        jitter=lambda: 0,
        originals=Path(tempfile.mkdtemp(prefix="floatchat-landing-test-")),
    )


def test_B03_durable_request_budget_shared_across_worker_claims():
    repository, store = Repository(), Store()
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise HTTPFailure(503)

    with pytest.raises(Rejection, match="http_retry_exhausted"):
        owner(repository, store, fail).obtain("/argo", {"id": "example"}, "profile")
    with pytest.raises(Rejection, match="http_retry_exhausted"):
        owner(repository, store, fail).obtain("/argo", {"id": "example"}, "profile")
    assert calls == repository.count == 4
    assert repository.finishes == [("http_failure", 503, "upstream_http_failure")] * 4


def test_B04_C10_partial_bytes_count_and_verified_landing_reuses_without_http():
    repository, store = Repository(), Store()
    calls = 0
    payload = b'[{"n":1.00,"api_key":"removed","source":"https://example.org/a?token=removed"}]'

    def transport(path, parameters, credential, account, **kwargs):
        nonlocal calls
        calls += 1
        account(7)
        if calls == 1:
            raise Rejection("upstream_transport_failure")
        account(len(payload))
        return Response(payload, len(payload) + 7, datetime.now(UTC), {})

    landed = owner(repository, store, transport).obtain("/argo", {"id": "example"}, "profile")
    replay = owner(repository, store, lambda *a, **kw: pytest.fail("Refetched verified raw"))
    assert replay.obtain("/argo", {"id": "example"}, "profile").payload == landed.payload
    assert repository.bytes_received == len(payload) + 14 and calls == repository.count == 2
    assert (
        b"1.00" in landed.payload
        and b"api_key" not in landed.payload
        and b"token=" not in landed.payload
    )
    assert repository.manifest["key"].startswith("raw/sha256/")


@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_B03_nonretryable_status_never_multiplies_attempts(status):
    repository = Repository()

    def transport(*args, **kwargs):
        raise HTTPFailure(status)

    with pytest.raises(Rejection):
        owner(repository, Store(), transport).obtain("/argo", {"id": "example"}, "profile")
    assert repository.count == 1


def test_D02_live_disabled_reserves_no_attempt_and_forwards_no_credential():
    repository = Repository()
    request = owner(
        repository, Store(), lambda *a, **kw: pytest.fail("Live access"), enabled=lambda: False
    )
    with pytest.raises(Rejection, match="live_ingestion_disabled"):
        request.obtain("/argo", {"id": "example"}, "profile")
    assert repository.count == 0


def test_C10_corrupt_landing_fails_instead_of_refetching_or_empty_success():
    repository, store = Repository(), Store()
    response = Response(b"[]", 2, datetime.now(UTC), {})
    request = owner(repository, store, lambda *a, **kw: response)
    landed = request.obtain("/argo", {"id": "example"}, "profile")
    store.data[landed.manifest["key"]] = b"[{}]"
    with pytest.raises(Rejection, match="landing_unavailable"):
        owner(repository, store, lambda *a, **kw: pytest.fail("Refetch")).obtain(
            "/argo", {"id": "example"}, "profile"
        )
    assert repository.count == 1


def test_B05_raw_response_representation_never_exposes_bytes_or_headers():
    response = Response(
        b"synthetic-private-response",
        26,
        datetime.now(UTC),
        {"untrusted": "synthetic-private-header"},
    )
    assert "synthetic-private" not in repr(response)
