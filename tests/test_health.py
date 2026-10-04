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
