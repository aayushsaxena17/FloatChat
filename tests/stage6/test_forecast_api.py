"""The forecast endpoints over memory stores: creation as a job, listing, detail, scoping."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from floatchat_api.jobs_api import JobsRuntime
from floatchat_api.main import create_app
from floatchat_core.forecast.model import BOUNDARY_TEXT
from floatchat_core.forecast.store import MemoryForecastStore
from floatchat_core.jobs.model import JobLimits
from floatchat_core.jobs.store import MemoryJobStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2"))
from test_api import FakeService  # noqa: E402

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
HEADERS = {"X-FloatChat-Client": "browser-1"}
REQUEST: dict[str, Any] = {
    "variable": "temperature",
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "depth_dbar": {"min": 0, "max": 100},
    "horizon": 3,
}


@pytest.fixture
def stores() -> tuple[MemoryJobStore, MemoryForecastStore]:
    return MemoryJobStore(clock=lambda: NOW), MemoryForecastStore()


@pytest.fixture
def client(stores) -> TestClient:
    jobs, forecasts = stores
    runtime = JobsRuntime(store=jobs, limits=JobLimits(), signing_key="k" * 32, clock=lambda: NOW)
    return TestClient(
        create_app(query_service=FakeService(), jobs_runtime=runtime, forecast_store=forecasts),
        raise_server_exceptions=False,
    )


def test_a_forecast_request_creates_a_forecast_job_and_a_definition(client, stores) -> None:
    jobs, forecasts = stores
    created = client.post("/v1/forecasts", json=REQUEST, headers=HEADERS)
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["created"] is True and body["job"]["kind"] == "forecast"
    assert body["job"]["queue"] == "forecast" and body["job"]["state"] == "queued"
    assert body["job"]["request"]["schema"] == "forecast-request-v1"
    definition = body["definition"]
    assert definition["variable"] == "temperature" and definition["region"] == "Arabian Sea"
    assert definition["aggregation"] == "profile_balanced_mean" and definition["min_profiles"] == 5
    assert definition["series_end"] > definition["series_start"]
    # The same request attaches to the active job; a different horizon is a different job.
    again = client.post("/v1/forecasts", json=REQUEST, headers=HEADERS).json()
    assert again["attached"] is True and again["job"]["id"] == body["job"]["id"]
    assert again["definition"]["id"] == definition["id"]
    other = client.post("/v1/forecasts", json={**REQUEST, "horizon": 6}, headers=HEADERS).json()
    assert other["created"] is True and other["definition"]["id"] == definition["id"]
    assert jobs.get(body["job"]["id"]).kind == "forecast"


def test_invalid_forecast_requests_are_rejected(client) -> None:
    unknown = client.post(
        "/v1/forecasts",
        json={**REQUEST, "geography": {"kind": "named_region", "value": "Atlantis"}},
        headers=HEADERS,
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_region"
    bad = client.post("/v1/forecasts", json={**REQUEST, "variable": "oxygen"}, headers=HEADERS)
    assert bad.status_code == 400
    bbox = client.post(
        "/v1/forecasts",
        json={
            **REQUEST,
            "geography": {"kind": "bbox", "west": 60, "south": 10, "east": 65, "north": 15},
        },
        headers=HEADERS,
    )
    assert bbox.status_code == 422 and bbox.json()["error"]["code"] == "plan_invalid"
    assert client.post("/v1/forecasts", json=REQUEST).json()["error"]["code"] == "client_required"


def test_listing_and_detail_are_scoped_and_carry_the_boundary_text(client, stores) -> None:
    jobs, forecasts = stores
    created = client.post("/v1/forecasts", json=REQUEST, headers=HEADERS).json()
    run = forecasts.create_run(created["definition"]["id"], "browser-1", created["job"]["id"], 3)
    forecasts.update_run(
        run.id,
        status="published",
        history={"months": ["2025-01"], "values": [28.0], "filled": [False], "counts": [9]},
        forecast={
            "months": ["2025-02"],
            "mean": [28.1],
            "lower80": [27.9],
            "upper80": [28.3],
            "lower95": [27.7],
            "upper95": [28.5],
        },
        backtest={"results": {}},
        limitations=BOUNDARY_TEXT,
        generated_at=NOW,
    )
    listed = client.get("/v1/forecasts", headers=HEADERS).json()["forecasts"]
    assert [row["id"] for row in listed] == [run.id] and listed[0]["status"] == "published"
    detail = client.get(f"/v1/forecasts/{run.id}", headers=HEADERS).json()
    assert detail["run"]["forecast"]["mean"] == [28.1]
    assert detail["definition"]["region"] == "Arabian Sea" and detail["model"] is None
    assert (
        detail["boundary"] == BOUNDARY_TEXT
        and "not a physics-based" in detail["run"]["limitations"]
    )
    other = {"X-FloatChat-Client": "browser-2"}
    assert client.get("/v1/forecasts", headers=other).json()["forecasts"] == []
    missing = client.get(f"/v1/forecasts/{run.id}", headers=other)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "forecast_not_found"
    assert client.get("/v1/forecasts/not-a-uuid", headers=HEADERS).status_code == 404
