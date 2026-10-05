import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from floatchat_api.main import create_app


async def usable() -> None:
    pass


def test_ready_and_live() -> None:
    client = TestClient(create_app(dict.fromkeys(["database", "redis", "storage"], usable)))
    assert client.get("/v1/health/live").json() == {"status": "ok"}
    assert client.get("/v1/health/ready").status_code == 200


@pytest.mark.parametrize("dependency", ["database", "redis", "storage"])
def test_dependency_outage_and_recovery(dependency: str) -> None:
    async def failed() -> None:
        raise RuntimeError("sensitive diagnostic must never be returned")

    probes = dict.fromkeys(["database", "redis", "storage"], usable)
    probes[dependency] = failed
    client = TestClient(create_app(probes))
    assert client.get("/v1/health/live").status_code == 200
    response = client.get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    probes[dependency] = usable
    assert client.get("/v1/health/ready").status_code == 200


def test_bounded_timeout() -> None:
    async def slow() -> None:
        await asyncio.sleep(5)

    client = TestClient(create_app({"database": slow}, timeout=0.05))
    start = time.monotonic()
    assert client.get("/v1/health/ready").status_code == 503
    assert time.monotonic() - start < 1


def test_live_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(create_app())
    assert client.get("/v1/health/live").status_code == 200
    assert client.get("/v1/health/ready").status_code == 503


@pytest.mark.asyncio
async def test_stalled_query_cleanup_does_not_extend_readiness_deadline(monkeypatch) -> None:
    from floatchat_api import health
    from floatchat_core.config import Settings

    closed = asyncio.Event()
    query_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_finished = asyncio.Event()
    other_checks = set()

    class PGConnection:
        def finish(self):
            closed.set()

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            query_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cleanup_started.set()
                try:
                    await asyncio.sleep(1)
                finally:
                    cleanup_finished.set()
                raise

    class Connection:
        pgconn = PGConnection()

        def cursor(self):
            return Cursor()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            closed.set()

    async def connect(*_args, **_kwargs):
        return Connection()

    async def other(name):
        other_checks.add(name)

    monkeypatch.setattr(health.psycopg.AsyncConnection, "connect", connect)
    settings = Settings(
        database_url="postgresql://unused@localhost/unused",
        redis_url="redis://localhost",
        object_storage_endpoint="http://localhost:9000",
        object_storage_access_key="local-test",
        object_storage_secret_key="local-test",
    )
    checks = health.dependency_checks(settings)
    checks.update(redis=lambda: other("redis"), storage=lambda: other("storage"))
    budget = 0.05
    start = time.monotonic()
    assert not await health.ready(checks, budget)
    elapsed = time.monotonic() - start
    # 50 ms allows event-loop scheduling; production's budget remains unchanged.
    assert elapsed <= budget + 0.05
    assert query_started.is_set() and other_checks == {"redis", "storage"}
    assert closed.is_set(), "Dispose the database socket before returning the response"
    await asyncio.wait_for(cleanup_started.wait(), 0.1)
    await asyncio.wait_for(cleanup_finished.wait(), 0.2)
    await asyncio.sleep(0)
    assert not health._cleanup_tasks


@pytest.mark.asyncio
async def test_cancelled_readiness_request_reclaims_probes() -> None:
    from floatchat_api import health

    entered = asyncio.Event()
    exited = asyncio.Event()

    async def probe():
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            exited.set()

    request = asyncio.create_task(health.ready({"database": probe}, 4))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    await asyncio.wait_for(exited.wait(), 0.2)
    await asyncio.sleep(0)
    assert not health._cleanup_tasks
