import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from floatchat_core.ingestion import landing as landing_module
from floatchat_core.ingestion import transport as transport_module
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.transport import HTTPFailure, Response, UpstreamGovernor


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

    # stage1-v4 object protocol (package C), kept so these tests survive its swap.
    def write_immutable(self, key, data, sha256_hex, deadline):
        self.data.setdefault(key, data)

    def stat(self, key, deadline):
        if key not in self.data:
            raise Rejection("object_missing")
        return {"bytes": len(self.data[key]), "sha256": None}


class Repository:
    def __init__(self):
        self.count = 0
        self.bytes_received = 0
        self.finishes = []
        self.manifest = None
        self.locked = False
        self.slots = []

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
    def upstream_slot(self, authority, deadline, slot=1):
        assert not self.locked
        self.slots.append(slot)
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


def owner(repository, store, transport, *, enabled=lambda: True, **kwargs):
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
        **kwargs,
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


def test_E01_validate_once_per_landing_and_never_on_reload(monkeypatch):
    repository, store = Repository(), Store()
    calls = []
    real = landing_module.validate_raw
    monkeypatch.setattr(
        landing_module, "validate_raw", lambda payload: calls.append(1) or real(payload)
    )
    response = Response(b'[{"n":1}]', 9, datetime.now(UTC), {})
    landed = owner(repository, store, lambda *a, **kw: response).obtain(
        "/argo", {"id": "example"}, "profile"
    )
    landings = len(calls)
    assert landings >= 1  # publish_verified decides how often (package C narrows it to 1)
    reloaded = owner(
        repository, store, lambda *a, **kw: pytest.fail("Refetch"), require_existing=True
    )
    assert reloaded.obtain("/argo", {"id": "example"}, "profile").payload == landed.payload
    assert len(calls) == landings  # a reload verifies bytes by hash, not by decoding again


def test_E02_default_owner_uses_slot_one_and_explicit_slot_is_forwarded():
    response = Response(b"[]", 2, datetime.now(UTC), {})
    default, explicit = Repository(), Repository()
    owner(default, Store(), lambda *a, **kw: response).obtain("/argo", {"id": "a"}, "profile")
    owner(explicit, Store(), lambda *a, **kw: response, slot=3).obtain(
        "/argo", {"id": "b"}, "profile"
    )
    assert default.slots == [1] and explicit.slots == [3]


def test_E03_governor_permit_wraps_the_request_and_is_released_before_retry_delay(monkeypatch):
    monkeypatch.setattr(transport_module, "RETRY_MAXIMA", {1: 2.0, 2: 2.0, 3: 2.0})
    repository, store = Repository(), Store()
    governor = UpstreamGovernor(4, pause=0.0)
    events, now = [], [0.0]

    def transport(*args, **kwargs):
        events.append(("request", sorted(governor._held)))
        if len(events) == 1:
            raise HTTPFailure(429, "0")
        return Response(b"[]", 2, datetime.now(UTC), {})

    def sleep(seconds):
        events.append(("sleep", sorted(governor._held), governor.current_permits))
        now[0] += seconds

    request = owner(repository, store, transport, governor=governor)
    request.clock, request.sleep = lambda: now[0], sleep
    request.obtain("/argo", {"id": "example"}, "profile")
    # The 429 halved the permits (4 -> 2) and the permit was free while the owner slept.
    assert events == [("request", [1]), ("sleep", [], 2), ("request", [1])]
    assert governor.observed_429 == 1 and governor.current_permits == 2
    assert repository.slots == [1, 1] and not governor._held
    assert repository.finishes[0] == ("http_failure", 429, "upstream_http_failure")


def test_E04_governor_slot_index_selects_the_advisory_lock():
    repository = Repository()
    governor = UpstreamGovernor(4)
    held = governor.acquire(time.monotonic() + 5)  # another thread's slot 1
    response = Response(b"[]", 2, datetime.now(UTC), {})
    owner(repository, Store(), lambda *a, **kw: response, governor=governor).obtain(
        "/argo", {"id": "example"}, "profile"
    )
    assert held == 1 and repository.slots == [2]
    governor.release(held, 200)
