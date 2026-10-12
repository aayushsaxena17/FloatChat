"""A running query no longer holds the event loop (ADR-0066): health and reads answer meanwhile."""

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from floatchat_api.main import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2"))
from test_api import QUERY  # noqa: E402  (the contract tests' valid query response)


class SlowService:
    """Only what the query route calls; the query blocks a thread like DuckDB would."""

    def __init__(self) -> None:
        self.started = threading.Event()

    def query(self, payload: Any) -> dict[str, Any]:
        self.started.set()
        time.sleep(1.5)
        return QUERY


async def _scenario() -> tuple[float, float]:
    service = SlowService()
    app = create_app(query_service=service)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slow = asyncio.create_task(client.post("/v1/query", json={"dataset": "core"}))
        # The query blocks a worker thread; wait for it from another thread, not the loop.
        assert await asyncio.to_thread(service.started.wait, 5)
        began = time.monotonic()
        live = await client.get("/v1/health/live")
        live_ms = (time.monotonic() - began) * 1000
        assert live.status_code == 200
        response = await slow
        assert response.status_code == 200
        return live_ms, (time.monotonic() - began) * 1000


def test_health_answers_while_a_query_runs() -> None:
    live_ms, slow_remaining_ms = asyncio.run(_scenario())
    # Before ADR-0066 the health call waited for the whole 1.5 s query.
    assert live_ms < 300, live_ms
    assert slow_remaining_ms > 1000
