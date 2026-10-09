"""Threaded transport, adaptive governor and metadata cache controls.

Sockets are local socketpairs and every repository/store is a fake: no network, no
signals. Synthetic sentinels only; no credential is real.
"""

import hashlib
import http.client
import json
import signal
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from floatchat_core.ingestion import landing as landing_module
from floatchat_core.ingestion import transport as transport_module
from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.landing import CACHE_WINDOW, RequestOwner, cache_fresh
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.raw import sanitize_raw
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.source import RecordedSource
from floatchat_core.ingestion.transport import (
    HTTPFailure,
    Response,
    UpstreamGovernor,
    fetch,
    operation_deadline,
    read_body,
    tls_context,
)

SENTINEL = "synthetic-test-sentinel"
BODY = b'[{"_id":"a"}]'


# --- fetch from worker threads over local socket pairs --------------------------------


def read_request(server):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = server.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


class FakeConnection(http.client.HTTPConnection):
    """PinnedConnection stand-in whose far end is `script(server_socket)`."""

    script = None
    refuse = None

    def __init__(self, address, timeout, *, until=None):
        super().__init__("argovis-api.colorado.edu", 443, timeout=timeout)
        self.address, self.until = address, until

    def connect(self):
        if type(self).refuse is not None:
            raise type(self).refuse
        client, server = socket.socketpair()
        self.sock = client
        threading.Thread(target=type(self).script, args=(server,), daemon=True).start()


@pytest.fixture
def wire_fake(monkeypatch):
    seen = []
    signals = []
    for name in ("signal", "setitimer", "alarm"):
        original = getattr(signal, name)
        monkeypatch.setattr(
            signal,
            name,
            lambda *args, _name=name, _original=original, **kw: (
                signals.append(_name) or _original(*args, **kw)
            ),
        )

    def serve(body=BODY, status="200 OK", extra=""):
        def script(server):
            seen.append(read_request(server))
            head = (
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n{extra}"
                f"Content-Length: {len(body)}\r\n\r\n"
            )
            server.sendall(head.encode() + body)
            server.close()

        FakeConnection.script = script

    FakeConnection.refuse = None
    monkeypatch.setattr(transport_module, "PinnedConnection", FakeConnection)
    monkeypatch.setattr(transport_module, "public_addresses", lambda: ("93.184.216.34",))
    serve()
    yield type("Wire", (), {"seen": seen, "signals": signals, "serve": staticmethod(serve)})
    FakeConnection.script = FakeConnection.refuse = None


def in_thread(function, *args, **kwargs):
    box = {}

    def target():
        box["thread"] = threading.current_thread()
        try:
            box["value"] = function(*args, **kwargs)
        except BaseException as error:  # noqa: BLE001 - re-raised by the caller
            box["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(15)
    assert not thread.is_alive()
    return box


def fetch_once(parameters=None, **kwargs):
    return fetch(
        "/argo",
        parameters or {"id": "a"},
        SENTINEL,
        kwargs.pop("account", lambda size: None),
        deadline=kwargs.pop("deadline", time.monotonic() + 30),
        enabled=kwargs.pop("enabled", lambda: True),
        **kwargs,
    )


def test_E01_fetch_runs_in_a_worker_thread_without_signals(wire_fake):
    counted = []
    box = in_thread(fetch_once, account=counted.append)
    assert "error" not in box and box["thread"] is not threading.main_thread()
    response = box["value"]
    assert response.payload == BODY and response.status == 200 and sum(counted) == len(BODY)
    request = wire_fake.seen[0].decode()
    assert request.startswith("GET /argo?id=a HTTP/1.1")
    assert f"x-argokey: {SENTINEL}" in request and "Connection: close" in request
    assert "Host: argovis-api.colorado.edu" in request
    assert wire_fake.signals == []
    assert SENTINEL not in repr(response)


def test_E01_empty_delivery_404_and_nonempty_404_keep_their_meaning(wire_fake):
    parameters = {"startDate": "a", "endDate": "b", "polygon": "[]"}
    wire_fake.serve(b"[]", "404 Not Found")
    empty = in_thread(fetch_once, parameters)["value"]
    assert empty.status == 404 and empty.payload == b"[]"
    wire_fake.serve(b'{"code":404}', "404 Not Found")
    error = in_thread(fetch_once, parameters)["error"]
    assert isinstance(error, HTTPFailure) and error.status == 404 and error.retryable is False
    wire_fake.serve(b"[]", "429 Too Many Requests", "Retry-After: 7\r\n")
    error = in_thread(fetch_once)["error"]
    assert isinstance(error, HTTPFailure) and error.status == 429 and error.retry_after == "7"


def test_E01_connection_close_response_is_read_after_the_socket_closes(wire_fake):
    # Argovis answers "Connection: close": http.client closes the socket at the end of
    # the body, and the per-read timeout refresh must not turn that into a failure.
    parameters = {"startDate": "a", "endDate": "b", "polygon": "[]"}
    for body, status, wanted in ((BODY, "200 OK", 200), (b"[\n\n]\n", "404 Not Found", 404)):
        wire_fake.serve(body, status, "Connection: close\r\n")
        box = in_thread(fetch_once, parameters)
        assert "error" not in box, box.get("error")
        assert box["value"].status == wanted and box["value"].payload == body


def test_E01_redirect_and_live_flag_are_checked_without_signals(wire_fake):
    wire_fake.serve(b"", "302 Found", "Location: https://elsewhere.invalid/?k=secret\r\n")
    error = in_thread(fetch_once)["error"]
    assert isinstance(error, Rejection) and error.category == "upstream_redirect_rejected"
    assert "secret" not in repr(error) and "secret" not in str(error)
    error = in_thread(fetch_once, enabled=lambda: False)["error"]
    assert error.category == "live_ingestion_disabled"
    flags = iter([True, True, False])
    wire_fake.serve()
    error = in_thread(fetch_once, enabled=lambda: next(flags, False))["error"]
    assert error.category == "live_ingestion_disabled"


def test_E01_concurrent_fetches_share_no_state(wire_fake):
    results = []

    def one():
        results.append(in_thread(fetch_once))

    threads = [threading.Thread(target=one) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert len(results) == 6 and all(r["value"].payload == BODY for r in results)
    assert len({r["thread"] for r in results}) == 6 and wire_fake.signals == []


def test_E01_idle_read_expires_through_the_socket_timeout(wire_fake, monkeypatch):
    monkeypatch.setattr(transport_module, "IDLE_READ", 0.2)
    release = threading.Event()

    def stall(server):
        read_request(server)
        server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n")
        server.sendall(b"Content-Length: 100\r\n\r\n[{")
        release.wait(5)
        server.close()

    FakeConnection.script = stall
    started = time.monotonic()
    error = in_thread(fetch_once)["error"]
    release.set()
    assert isinstance(error, Rejection) and error.category == "upstream_transport_failure"
    assert 0.15 <= time.monotonic() - started < 3
    assert wire_fake.signals == []


def test_E01_attempt_bound_expires_between_reads_as_io_deadline(wire_fake, monkeypatch):
    monkeypatch.setattr(transport_module, "ATTEMPT_BOUND", 0.5)
    release = threading.Event()
    block = b"x" * 65536

    def slow(server):
        read_request(server)
        server.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {4 * len(block)}\r\n\r\n".encode()
        )
        for _ in range(4):
            server.sendall(block)
            if release.wait(0.3):
                return

    FakeConnection.script = slow
    started = time.monotonic()
    error = in_thread(fetch_once)["error"]
    release.set()
    assert isinstance(error, Rejection) and error.category == "io_deadline"
    assert time.monotonic() - started < 5 and wire_fake.signals == []


def test_E01_run_deadline_binds_when_shorter_than_the_attempt_bound(wire_fake):
    error = in_thread(fetch_once, deadline=time.monotonic() - 1)["error"]
    assert isinstance(error, Rejection) and error.category == "io_deadline"


def test_E01_read_returning_after_the_bound_is_rejected():
    now = [0.0]
    response = Mock()
    response.getheaders.return_value = []
    response.getheader.side_effect = lambda key, default=None: default

    def read(size):
        now[0] += 6
        return b"x"

    response.read.side_effect = read

    def tick():
        if now[0] >= 10:
            raise Rejection("io_deadline")

    accounted = []
    with pytest.raises(Rejection, match="io_deadline"):
        read_body(response, accounted.append, tick=tick)
    assert response.read.call_count == 2  # the late second read returned, then was refused
    assert accounted == [1, 1]  # and its bytes were still charged before the refusal


def test_E01_attempt_bound_during_an_empty_receipt_is_not_a_permanent_404():
    response = Mock()
    response.getheaders.return_value = []
    response.getheader.side_effect = lambda key, default=None: (
        "application/json" if key == "Content-Type" else default
    )
    response.read.return_value = b"[]"

    def expired():
        raise Rejection("io_deadline")

    with pytest.raises(Rejection, match="io_deadline"):
        transport_module.empty_receipt(response, lambda size: None, lambda: True, expired)


def test_E01_connect_phase_timeout_and_refusal_have_distinct_categories(wire_fake):
    FakeConnection.refuse = TimeoutError()
    assert in_thread(fetch_once)["error"].category == "io_deadline"
    FakeConnection.refuse = ConnectionRefusedError()
    assert in_thread(fetch_once)["error"].category == "upstream_transport_failure"


def test_E01_dns_budget_overrun_is_io_deadline(wire_fake, monkeypatch):
    monkeypatch.setattr(transport_module, "CONNECT_BUDGET", 0.05)
    monkeypatch.setattr(
        transport_module, "public_addresses", lambda: time.sleep(0.15) or ("93.184.216.34",)
    )
    FakeConnection.refuse = AssertionError("must not connect after the budget is spent")
    assert in_thread(fetch_once)["error"].category == "io_deadline"


def test_E01_tls_context_is_shared_and_pinned_connection_keeps_its_signature():
    assert tls_context() is tls_context()
    connection = transport_module.PinnedConnection("93.184.216.34", 10)
    assert connection.address == "93.184.216.34" and connection.until is None
    assert transport_module.PinnedConnection("93.184.216.34", 3, until=5.0).until == 5.0


def test_E02_operation_deadline_is_thread_safe_and_never_touches_signals(wire_fake):
    def bounded(seconds):
        with operation_deadline(time.monotonic() + seconds):
            return threading.current_thread()

    box = in_thread(bounded, 5)
    assert box["value"] is box["thread"] and box["thread"] is not threading.main_thread()
    assert in_thread(bounded, -1)["error"].category == "io_deadline"

    def overrun():
        with operation_deadline(time.monotonic() + 0.05):
            time.sleep(0.1)

    assert in_thread(overrun)["error"].category == "io_deadline"

    def failing():
        with operation_deadline(time.monotonic() + 0.05):
            time.sleep(0.1)
            raise ValueError("body error")

    assert isinstance(in_thread(failing)["error"], ValueError)  # not masked by the exit check
    assert wire_fake.signals == []
    # Nested and overlapping use (the old alarm refused it) is simply allowed.
    with operation_deadline(time.monotonic() + 5), operation_deadline(time.monotonic() + 5):
        pass


# --- governor ---------------------------------------------------------------------------


def soon(seconds=5.0):
    return time.monotonic() + seconds


def test_E03_slots_are_the_lowest_free_index_and_limited_to_the_permits():
    governor = UpstreamGovernor(3, pause=0)
    assert [governor.acquire(soon()) for _ in range(3)] == [1, 2, 3]
    with pytest.raises(Rejection, match="upstream_slot_deadline"):
        governor.acquire(soon(0.05))
    governor.release(2, 200)
    assert governor.acquire(soon()) == 2
    with pytest.raises(Rejection, match="invalid_upstream_slot"):
        governor.release(9, 200)
    for permits in (0, 65):
        with pytest.raises(Rejection, match="invalid_upstream_slot"):
            UpstreamGovernor(permits)


def test_E03_429_halves_to_a_floor_of_one_and_counts():
    governor = UpstreamGovernor(8, pause=0)
    seen = []
    for _ in range(5):
        governor.release(governor.acquire(soon()), 429)
        seen.append(governor.current_permits)
    assert seen == [4, 2, 1, 1, 1]
    assert governor.snapshot() == {
        "maximum_permits": 8,
        "current_permits": 1,
        "lowest_permits": 1,
        "observed_429": 5,
        "restored_permits": 0,
    }


def test_E03_restores_one_permit_per_twenty_non_429_completions_up_to_the_maximum():
    governor = UpstreamGovernor(4, pause=0)
    governor.release(governor.acquire(soon()), 429)
    assert governor.current_permits == 2

    def complete(count, status=200):
        for _ in range(count):
            governor.release(governor.acquire(soon()), status)

    complete(19)
    assert governor.current_permits == 2
    complete(1, None)  # a completion without a status counts too
    assert governor.current_permits == 3
    complete(20, 503)
    assert governor.current_permits == 4
    complete(60)
    assert governor.current_permits == 4 and governor.snapshot()["restored_permits"] == 2
    governor.release(governor.acquire(soon()), 429)
    complete(10)
    governor.release(governor.acquire(soon()), 429)  # a 429 resets the streak
    complete(19)
    assert governor.current_permits == 1
    complete(1)
    assert governor.current_permits == 2


def test_E03_429_blocks_new_acquires_for_sixty_seconds_or_retry_after():
    for retry_after, expected in ((None, 60), (10, 60), (100, 100)):
        governor = UpstreamGovernor(2)
        slot = governor.acquire(soon())
        before = time.monotonic()
        governor.release(slot, 429, retry_after)
        assert expected <= governor.blocked_until - before < expected + 1
        with pytest.raises(Rejection, match="upstream_slot_deadline"):
            governor.acquire(soon(0.05))
    # A pause that is not the binding limit does not delay unrelated successes.
    governor = UpstreamGovernor(2)
    assert governor.acquire(soon()) == 1


def test_E03_blocked_acquire_resumes_when_the_pause_ends():
    governor = UpstreamGovernor(2, pause=0.3)
    governor.release(governor.acquire(soon()), 429)
    started = time.monotonic()
    assert governor.acquire(soon()) == 1
    assert 0.2 <= time.monotonic() - started < 3


def test_E03_halving_waits_for_in_flight_holders_to_drain():
    governor = UpstreamGovernor(4, pause=0)
    held = [governor.acquire(soon()) for _ in range(3)]
    governor.release(held[2], 429)  # 4 -> 2 while slots 1 and 2 are still in flight
    with pytest.raises(Rejection, match="upstream_slot_deadline"):
        governor.acquire(soon(0.05))
    governor.release(held[0], 200)
    assert governor.acquire(soon()) == 1


def test_E03_acquire_blocks_until_release_and_hands_over_the_slot():
    governor = UpstreamGovernor(1, pause=0)
    first = governor.acquire(soon())
    result = []
    thread = threading.Thread(target=lambda: result.append(governor.acquire(soon())))
    thread.start()
    time.sleep(0.15)
    assert result == []
    governor.release(first, 200)
    thread.join(5)
    assert result == [1]


def test_E03_threads_never_exceed_the_permits_or_share_a_slot():
    governor = UpstreamGovernor(3, pause=0)
    active, peak, problems, guard = set(), [0], [], threading.Lock()

    def worker(index):
        for step in range(25):
            slot = governor.acquire(soon(20))
            with guard:
                if slot in active or not 1 <= slot <= 3:
                    problems.append(slot)
                active.add(slot)
                peak[0] = max(peak[0], len(active))
            time.sleep(0.001)
            with guard:
                active.discard(slot)
            governor.release(slot, 429 if (index, step) == (0, 5) else 200)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads)
    assert problems == [] and peak[0] <= 3 and governor.observed_429 == 1


def test_E03_waiting_acquire_pulses_and_can_be_stopped():
    governor = UpstreamGovernor(1, pause=0)
    held = governor.acquire(soon())
    governor.pulse = 0.05
    pulses = []
    thread = threading.Thread(
        target=lambda: governor.release(governor.acquire(soon(), lambda: pulses.append(1)), 200)
    )
    thread.start()
    time.sleep(0.3)
    governor.release(held, 200)
    thread.join(5)
    assert len(pulses) >= 2

    def stop():
        raise Rejection("live_ingestion_disabled")

    held = governor.acquire(soon())
    with pytest.raises(Rejection, match="live_ingestion_disabled"):
        governor.acquire(soon(), stop)
    governor.release(held, 200)


# --- metadata cache ---------------------------------------------------------------------

ENVIRONMENT, RUN = uuid.uuid4(), uuid.uuid4()
# The acceptance reference time T (in the past) differs from the run's actual creation
# time: the cache window is anchored on the latter and must ignore T.
REFERENCE = datetime(2025, 4, 1, tzinfo=UTC)
CREATED = datetime(2026, 10, 8, 12, tzinfo=UTC)
META = ("/argo/meta", {"id": "m1"}, "metadata")
CACHED = b'[{"_id":"m1","n":1.00}]'


class Store:
    def __init__(self):
        self.data, self.writes = {}, []

    def write_temporary(self, key, payload, deadline):
        self.writes.append(key)
        self.data[key] = payload

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])

    def write_immutable(self, key, data, sha256_hex, deadline):
        self.writes.append(key)
        self.data.setdefault(key, data)

    def stat(self, key, deadline):
        return {"bytes": len(self.data[key]), "sha256": None}

    def read(self, key, max_bytes, deadline):
        if key not in self.data:
            raise Rejection("object_missing")
        return self.data[key]


class Repository:
    """Per-chunk manifests plus the environment-wide cache, as the real tables do."""

    def __init__(self):
        self.manifests, self.by_id, self.cache, self.pending = {}, {}, {}, {}
        self.run_reads = self.cache_gets = self.http = 0
        self.reserved, self.puts = [], []

    def run(self, identifier):
        self.run_reads += 1
        return {
            "environment_id": ENVIRONMENT,
            "run_reference_time_utc": REFERENCE,
            "created_at_actual_utc": CREATED,
        }

    def verified_landing(self, authority, key):
        return self.manifests.get((authority.chunk, key))

    def http_reserve(self, authority, key, role, parameters):
        self.http += 1
        attempt = uuid.uuid4()
        self.pending[attempt] = (authority.chunk, key)
        return attempt, 1

    def recorded_reserve(self, authority, key, role, parameters, origin):
        attempt = uuid.uuid4()
        self.pending[attempt] = (authority.chunk, key)
        self.reserved.append((authority.chunk, role, origin))
        return attempt

    def heartbeat(self, authority):
        pass

    def account_received(self, authority, attempt, count):
        pass

    @contextmanager
    def upstream_slot(self, authority, deadline, slot=1):
        yield

    def finish_attempt(
        self, authority, attempt, disposition, status=None, error=None, manifest=None
    ):
        if manifest:
            row = {**manifest, "object_key": manifest["key"]}
            self.manifests[self.pending[attempt]] = row
            self.by_id[manifest["id"]] = row

    def metadata_cache_get(self, environment, pointer):
        self.cache_gets += 1
        return self.cache.get((environment, pointer))

    def metadata_cache_put(self, environment, pointer, raw_manifest, run, retrieved_at):
        self.puts.append((pointer, raw_manifest, run))
        manifest = self.by_id[str(raw_manifest)]
        self.cache[(environment, pointer)] = {
            "environment_id": environment,
            "pointer": pointer,
            "raw_manifest_id": raw_manifest,
            "run_id": run,
            "retrieved_at": retrieved_at,
            "object_key": manifest["key"],
            "sha256": manifest["sha256"],
            "bytes": manifest["bytes"],
            "versions": manifest["versions"],
            "http_status": manifest["http_status"],
        }


@pytest.fixture
def cache_world(tmp_path):
    repository, store = Repository(), Store()
    calls = []

    def transport(path, parameters, credential, account, **kwargs):
        calls.append(parameters["id"])
        account(len(CACHED))
        return Response(CACHED, len(CACHED), retrieved, {})

    retrieved = CREATED + timedelta(minutes=5)  # landed during this run

    def owner(chunk=None, *, require_existing=False, transport=transport):
        return RequestOwner(
            repository,
            store,
            Authority(RUN, chunk or uuid.uuid4(), 1, 1),
            deadline=time.monotonic() + 60,
            application_commit="offline-test",
            enabled=lambda: True,
            credential=lambda: SENTINEL,
            transport=transport,
            jitter=lambda: 0,
            originals=tmp_path / "originals",
            require_existing=require_existing,
        )

    class World:
        pass

    world = World()
    world.repository, world.store, world.calls, world.owner = repository, store, calls, owner
    return world


def landing_count(monkeypatch):
    calls = []
    real = landing_module.validate_raw
    monkeypatch.setattr(
        landing_module, "validate_raw", lambda payload: calls.append(1) or real(payload)
    )
    return calls


@pytest.mark.parametrize(
    "offset,expected",
    [
        (timedelta(0), True),
        (-CACHE_WINDOW, True),
        (-CACHE_WINDOW - timedelta(microseconds=1), False),
        (-timedelta(days=20), True),
        (-timedelta(days=31), False),
        (timedelta(microseconds=1), True),  # landed after the run began: no upper bound
        (timedelta(days=3), True),
    ],
)
def test_E04_cache_freshness_is_a_lower_bound_thirty_days_before_run_creation(offset, expected):
    assert cache_fresh(CREATED + offset, CREATED) is expected


def test_E04_miss_fetches_then_upserts_the_chunk_manifest(cache_world):
    chunk = uuid.uuid4()
    landed = cache_world.owner(chunk).obtain(*META)
    assert landed.payload == sanitize_raw(CACHED).payload and cache_world.calls == ["m1"]
    ((pointer, raw_manifest, run),) = cache_world.repository.puts
    assert (pointer, str(raw_manifest), run) == ("m1", landed.manifest["id"], RUN)
    row = cache_world.repository.cache[(ENVIRONMENT, "m1")]
    assert row["retrieved_at"] == CREATED + timedelta(minutes=5) and row["http_status"] == 200


def test_E04_hit_records_a_per_chunk_manifest_without_http_or_publication(cache_world, monkeypatch):
    repository, store = cache_world.repository, cache_world.store
    first_chunk, second_chunk = uuid.uuid4(), uuid.uuid4()
    first = cache_world.owner(first_chunk).obtain(*META)
    writes, validations = list(store.writes), landing_count(monkeypatch)
    second_owner = cache_world.owner(second_chunk)
    second = second_owner.obtain(*META)
    assert cache_world.calls == ["m1"] and repository.http == 1  # no second request
    assert store.writes == writes and validations == []  # nothing published or decoded
    assert second.payload == first.payload
    assert repository.reserved == [(second_chunk, "metadata", "cache")]
    # A manifest of its own, pointing at the same object, so replay identity is per chunk.
    assert second.manifest["id"] != first.manifest["id"]
    for field in ("key", "sha256", "bytes", "retrieved_at", "http_status", "versions"):
        assert second.manifest[field] == first.manifest[field], field
    assert second.manifest["sanitization"]["input_origin"] == "cache"
    assert second.manifest["sanitization"]["cache_manifest"] == first.manifest["id"]
    assert (
        repository.verified_landing(
            Authority(RUN, second_chunk, 1, 1), landing_module.logical_request(*META)
        )
        is not None
    )
    # The cache row keeps pointing at the original landing; only misses upsert.
    assert len(repository.puts) == 1
    # The run row is read once per owner however many lookups it serves.
    second_owner.obtain("/argo/meta", {"id": "m2"}, "metadata")
    assert repository.run_reads == 2


def test_E04_verified_landing_finds_a_cache_hit_on_reload_without_the_cache(cache_world):
    repository = cache_world.repository
    cache_world.owner().obtain(*META)
    chunk = uuid.uuid4()
    hit = cache_world.owner(chunk).obtain(*META)
    gets, reads = repository.cache_gets, repository.run_reads

    def refuse(*args, **kwargs):
        pytest.fail("Reload must not request")

    reload = cache_world.owner(chunk, require_existing=True, transport=refuse).obtain(*META)
    assert reload.payload == hit.payload and reload.manifest["id"] == hit.manifest["id"]
    assert (repository.cache_gets, repository.run_reads) == (gets, reads)
    # A chunk without its own manifest cannot borrow the cache on reload.
    with pytest.raises(Rejection, match="landing_unavailable"):
        cache_world.owner(uuid.uuid4(), require_existing=True, transport=refuse).obtain(*META)


def test_E04_entries_from_earlier_runs_hit_within_thirty_days_and_stale_ones_are_replaced(
    cache_world,
):
    repository = cache_world.repository
    cache_world.owner().obtain(*META)
    row = repository.cache[(ENVIRONMENT, "m1")]
    row["retrieved_at"] = CREATED - timedelta(days=20)  # an earlier run's fetch
    before = len(cache_world.calls)
    cache_world.owner().obtain(*META)
    assert len(cache_world.calls) == before
    row["retrieved_at"] = CREATED - CACHE_WINDOW - timedelta(seconds=1)  # stale
    cache_world.owner().obtain(*META)
    assert len(cache_world.calls) == before + 1
    assert repository.cache[(ENVIRONMENT, "m1")]["retrieved_at"] == CREATED + timedelta(minutes=5)


def test_E04_the_reference_time_does_not_bound_evidence_freshness(cache_world):
    # T is 2025-04-01 while everything was fetched in 2026: still a hit within the run.
    assert CREATED - REFERENCE > CACHE_WINDOW
    cache_world.owner().obtain(*META)
    cache_world.owner().obtain(*META)
    assert cache_world.calls == ["m1"]


@pytest.mark.parametrize("damage", ["missing", "sha", "versions", "bytes"])
def test_E04_unverifiable_cached_object_is_a_miss_not_a_landing_failure(cache_world, damage):
    repository, store = cache_world.repository, cache_world.store
    cache_world.owner().obtain(*META)
    row = repository.cache[(ENVIRONMENT, "m1")]
    if damage == "missing":
        del store.data[row["object_key"]]
    elif damage == "sha":
        row["sha256"] = "0" * 64
    elif damage == "versions":
        row["versions"] = {}
    else:
        row["bytes"] += 1
    landed = cache_world.owner().obtain(*META)
    assert cache_world.calls == ["m1", "m1"] and landed.payload == sanitize_raw(CACHED).payload
    assert repository.reserved == []  # recorded as a normal request, not a cache hit
    assert store.data[landed.manifest["key"]] == landed.payload


def test_E04_only_metadata_requests_consult_the_cache(cache_world):
    repository = cache_world.repository
    cache_world.owner().obtain("/argo", {"id": "p1"}, "profile")
    cache_world.owner().obtain("/argo", {"id": "m1"}, "inventory_before")
    assert (repository.run_reads, repository.cache_gets, repository.puts) == (0, 0, [])


def test_E04_cache_is_per_environment(cache_world):
    repository = cache_world.repository
    cache_world.owner().obtain(*META)
    repository.cache[(uuid.uuid4(), "m1")] = repository.cache.pop((ENVIRONMENT, "m1"))
    cache_world.owner().obtain(*META)
    assert cache_world.calls == ["m1", "m1"]


# --- fixture-driven RecordedSource ------------------------------------------------------


def fixture_source(tmp_path, repository, store, chunk=None):
    root = tmp_path / "fx"
    root.mkdir(exist_ok=True)
    (root / "m1.json").write_bytes(CACHED)
    index = root / "index.json"
    index.write_text(
        json.dumps(
            {
                "kind": "synthetic_offline_chunk_fixture",
                "versions": policy_versions(),
                "responses": [
                    {
                        "role": "metadata",
                        "path": "/argo/meta",
                        "parameters": {"id": "m1"},
                        "file": "m1.json",
                        "sha256": hashlib.sha256(CACHED).hexdigest(),
                        "retrieved_at_utc": "2025-03-01T00:00:00+00:00",
                    }
                ],
            }
        )
    )
    descriptor = {
        "fixture_index": str(index),
        "fixture_root": str(root),
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
    }
    return RecordedSource(
        repository,
        store,
        Authority(RUN, chunk or uuid.uuid4(), 1, 1),
        descriptor,
        deadline=time.monotonic() + 60,
        application_commit="offline-test",
    )


def seed_cache(repository, store, payload=None):
    cleaned = sanitize_raw(CACHED).payload
    digest = hashlib.sha256(cleaned).hexdigest()
    key = f"raw/sha256/{digest}.json"
    store.data[key] = payload or cleaned
    repository.cache[(ENVIRONMENT, "m1")] = {
        "raw_manifest_id": uuid.uuid4(),
        "retrieved_at": CREATED - timedelta(days=3),
        "object_key": key,
        "sha256": digest,
        "bytes": len(cleaned),
        "versions": policy_versions(),
        "http_status": 200,
    }
    return key


def test_E05_fixture_path_never_consults_or_writes_the_cache(tmp_path):
    repository, store = Repository(), Store()
    seed_cache(repository, store)  # a fresh entry that a lookup would hit
    landed = fixture_source(tmp_path, repository, store).obtain(*META)
    assert store.writes and landed.manifest["sanitization"]["validation"]["documents"] == 1
    assert landed.manifest["sanitization"]["input_origin"] == "captured"
    assert landed.manifest["sanitization"]["input_kind"] == "synthetic_offline_chunk_fixture"
    assert repository.reserved[0][1:] == ("metadata", "captured")
    assert (repository.cache_gets, repository.run_reads, repository.puts) == (0, 0, [])


def test_E05_replay_never_consults_the_cache(tmp_path):
    repository, store = Repository(), Store()
    seed_cache(repository, store)
    predecessor = sanitize_raw(CACHED).payload
    key = "raw/sha256/" + hashlib.sha256(predecessor).hexdigest() + ".json"
    record = {
        "object_key": key,
        "bytes": len(predecessor),
        "sha256": hashlib.sha256(predecessor).hexdigest(),
        "versions": policy_versions(),
        "retrieved_at": REFERENCE - timedelta(days=9),
        "http_status": 200,
    }

    class Cursor:
        def execute(self, *args):
            pass

        def fetchone(self):
            return record

    @contextmanager
    def transaction(readonly_snapshot=False):
        yield Cursor()

    repository.transaction = transaction
    repository.chunk = lambda chunk: {
        "requested_start": REFERENCE,
        "requested_end": REFERENCE,
        "tile": {"west": 70, "south": 10, "width": 10, "height": 10},
    }
    source = RecordedSource(
        repository,
        store,
        Authority(RUN, uuid.uuid4(), 1, 1),
        {"predecessor_run": str(uuid.uuid4())},
        deadline=time.monotonic() + 60,
        application_commit="offline-test",
    )
    store.data[key] = predecessor
    landed = source.obtain(*META)
    assert repository.cache_gets == 0 and repository.run_reads == 0
    assert repository.reserved[0][2] == "replay"
    assert landed.manifest["sanitization"]["input_origin"] == "replay"
    assert landed.manifest["retrieved_at"] == record["retrieved_at"].isoformat()
