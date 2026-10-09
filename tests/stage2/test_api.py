"""Stage 2 API contract tests (plan sections 5 and 8) over an in-test ``QueryService`` double.

The double records the arguments ``query_api.py`` forwards, so parsing (timestamps, geography,
depth, paging) is asserted at the service boundary without a database. Real execution is covered
by the integration suite.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from floatchat_api.main import create_app
from floatchat_core.query.errors import REGISTRY, Detail, QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import BoundingBox, DepthRange, NamedRegion

HEADER = "X-Correlation-ID"
PROFILE_ID = "00000000-0000-4000-8000-000000000101"
ENVIRONMENT = {
    "id": "00000000-0000-4000-8000-000000000003",
    "name": "dev",
    "mode": "dev",
    "reference_time": "2025-04-01T00:00:00Z",
}
TABLE = {
    "columns": [{"name": "platform_number", "type": "string", "unit": None}],
    "rows": [["5900001"]],
    "row_count": 1,
    "missing_value_policy": "null",
    "non_finite_values": 0,
}
QC_POLICY = {"name": "science_ready", "version": "qc-policy-v1", "description": "good data"}
PARAMETERS = {
    "plan_schema": "stage2-plan-v1",
    "variables": [{"name": "temperature", "unit": "degree_Celsius"}],
    "limits": QueryLimits().public(),
}
COVERAGE = {
    "environment": ENVIRONMENT,
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "coverage": {"profiles": 3, "levels": 12},
    "slots": [{"month": "2025-01", "tile": "t1", "state": "covered"}],
}
FLOATS = {
    "environment": ENVIRONMENT,
    "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
    "geography": None,
    "result": TABLE,
    "next_cursor": "opaque-cursor",
}
FLOAT = {
    "environment": ENVIRONMENT,
    "float": {"platform_number": "5900001", "profile_count": 3},
    "trajectory": TABLE,
    "next_cursor": None,
}
PROFILES = {**FLOATS, "qc_policy": QC_POLICY, "next_cursor": None}
PROFILE = {
    "environment": ENVIRONMENT,
    "profile": {"id": PROFILE_ID, "platform_number": "5900001"},
    "qc_policy": QC_POLICY,
    "levels": TABLE,
}
QUERY = {
    "plan": {"dataset": "core"},
    "result": TABLE,
    "next_cursor": None,
    "chart": None,
    "coverage": {"profiles": 3},
    "partial": False,
    "missing": [],
    "execution": {"source": "postgresql", "elapsed_ms": 4, "rows": 1},
    "interpretation": {"summary": "profiles in the Arabian Sea"},
    "provenance": {"source": "argovis", "result_sha256": "0" * 64},
}
PLAN = {"dataset": "core", "variables": ["temperature"]}
# (method, path, the double's payload)
ENDPOINTS = [
    ("GET", "/v1/catalog/parameters", PARAMETERS),
    ("GET", "/v1/catalog/coverage", COVERAGE),
    ("GET", "/v1/floats", FLOATS),
    ("GET", "/v1/floats/5900001", FLOAT),
    ("GET", "/v1/profiles", PROFILES),
    ("GET", f"/v1/profiles/{PROFILE_ID}", PROFILE),
    ("POST", "/v1/query", QUERY),
]


class FakeService:
    """Implements the ``QueryService`` methods ``query_api.py`` calls; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.failure: Exception | None = None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.failure is not None:
            raise self.failure

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1][2]

    def parameters(self) -> dict[str, Any]:
        self._record("parameters")
        return PARAMETERS

    def coverage(self, **kwargs: Any) -> dict[str, Any]:
        self._record("coverage", **kwargs)
        return COVERAGE

    def floats(self, **kwargs: Any) -> dict[str, Any]:
        self._record("floats", **kwargs)
        return FLOATS

    def float_detail(self, platform_number: str, **kwargs: Any) -> dict[str, Any]:
        self._record("float_detail", platform_number, **kwargs)
        return FLOAT

    def profiles(self, **kwargs: Any) -> dict[str, Any]:
        self._record("profiles", **kwargs)
        return PROFILES

    def profile(self, profile_id: str, **kwargs: Any) -> dict[str, Any]:
        self._record("profile", profile_id, **kwargs)
        return PROFILE

    def query(self, payload: Any) -> dict[str, Any]:
        self._record("query", payload)
        return QUERY


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(service: FakeService) -> TestClient:
    # Unhandled exceptions must come back as the 500 envelope, not be re-raised into the test.
    return TestClient(create_app(query_service=service), raise_server_exceptions=False)


def send(client: TestClient, method: str, path: str, **kwargs: Any) -> Any:
    if method == "POST":
        kwargs.setdefault("json", PLAN)
    return client.request(method, path, **kwargs)


def error_of(response: Any, status: int, code: str) -> dict[str, Any]:
    """Assert the PRD 13.2 envelope and that its correlation ID matches the header."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "correlation_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)
    assert error["correlation_id"] == response.headers[HEADER]
    return error


# ----- every endpoint ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "payload"), ENDPOINTS)
def test_endpoint_returns_the_services_payload_and_a_correlation_id(
    client: TestClient, service: FakeService, method: str, path: str, payload: dict[str, Any]
) -> None:
    response = send(client, method, path)
    assert response.status_code == 200
    assert response.json() == payload
    uuid.UUID(response.headers[HEADER])  # generated when the client sends none
    assert len(service.calls) == 1


def test_health_endpoints_carry_the_correlation_id() -> None:
    async def usable() -> None:
        pass

    client = TestClient(create_app(dict.fromkeys(["database"], usable)))
    for path in ("/v1/health/live", "/v1/health/ready"):
        response = client.get(path)
        assert response.status_code == 200
        assert HEADER in response.headers


def test_docs_and_schema_stay_on(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "FloatChat"


# ----- correlation ID ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/health/live", "/v1/catalog/parameters"])
@pytest.mark.parametrize("token", ["a", "req-123_x.y:z", "A" * 64])
def test_ascii_token_is_echoed(client: TestClient, path: str, token: str) -> None:
    assert client.get(path, headers={HEADER: token}).headers[HEADER] == token


@pytest.mark.parametrize("path", ["/v1/health/live", "/v1/catalog/parameters"])
@pytest.mark.parametrize(
    "token",
    [
        "A" * 65,
        "has space",
        "semi;colon",
        "slash/path",
        "",
        "café".encode(),  # non-ASCII bytes
    ],
)
def test_other_values_are_replaced_by_a_uuid(
    client: TestClient, path: str, token: str | bytes
) -> None:
    response = client.get(path, headers={HEADER: token})
    generated = response.headers[HEADER]
    assert generated != token
    assert str(uuid.UUID(generated)) == generated


def test_token_with_a_trailing_newline_is_replaced(client: TestClient) -> None:
    generated = client.get("/v1/health/live", headers={HEADER: "abc\n"}).headers[HEADER]
    assert str(uuid.UUID(generated)) == generated


def test_generated_ids_differ_between_requests(client: TestClient) -> None:
    first = client.get("/v1/health/live").headers[HEADER]
    assert client.get("/v1/health/live").headers[HEADER] != first


def test_unknown_path_still_carries_the_header(client: TestClient) -> None:
    response = client.get("/v1/nothing", headers={HEADER: "keep-me"})
    assert response.status_code == 404
    assert response.headers[HEADER] == "keep-me"


# ----- query parameters: timestamps -------------------------------------------------------------

TIMED = [
    ("/v1/catalog/coverage", "coverage"),
    ("/v1/floats", "floats"),
    ("/v1/floats/5900001", "float_detail"),
    ("/v1/profiles", "profiles"),
]


@pytest.mark.parametrize(("path", "name"), TIMED)
def test_start_and_end_are_forwarded_as_aware_datetimes(
    client: TestClient, service: FakeService, path: str, name: str
) -> None:
    response = client.get(
        path, params={"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T05:30:00+05:30"}
    )
    assert response.status_code == 200
    assert service.calls[-1][0] == name
    assert service.last["start"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert service.last["end"] == datetime(2025, 2, 1, tzinfo=UTC)
    assert service.last["end"].utcoffset() == timedelta(hours=5, minutes=30)
    assert service.last["start"].tzinfo is not None


@pytest.mark.parametrize(("path", "name"), TIMED)
def test_timestamps_default_to_none(
    client: TestClient, service: FakeService, path: str, name: str
) -> None:
    assert client.get(path).status_code == 200
    assert service.last["start"] is None and service.last["end"] is None


@pytest.mark.parametrize("value", ["2025-01-01T00:00:00", "2025-01-01"])
@pytest.mark.parametrize("name", ["start", "end"])
@pytest.mark.parametrize(("path", "_"), TIMED)
def test_naive_timestamps_are_rejected(
    client: TestClient, service: FakeService, path: str, _: str, name: str, value: str
) -> None:
    response = client.get(path, params={name: value})
    error = error_of(response, 400, "invalid_parameter")
    assert [(d["field"], d["code"]) for d in error["details"]] == [(name, "invalid_time_range")]
    assert error["details"][0]["message"] == "timezone offset required"
    assert service.calls == []


def test_unparseable_timestamp_is_an_invalid_parameter(
    client: TestClient, service: FakeService
) -> None:
    error = error_of(
        client.get("/v1/floats", params={"start": "yesterday"}), 400, "invalid_parameter"
    )
    assert error["details"][0]["field"] == "start"
    assert service.calls == []


# ----- query parameters: geography --------------------------------------------------------------

GEOGRAPHIC = ["/v1/catalog/coverage", "/v1/floats", "/v1/profiles"]


@pytest.mark.parametrize("path", GEOGRAPHIC)
def test_region_becomes_a_named_region(client: TestClient, service: FakeService, path: str) -> None:
    assert client.get(path, params={"region": "Arabian Sea"}).status_code == 200
    assert service.last["geography"] == NamedRegion(kind="named_region", value="Arabian Sea")


@pytest.mark.parametrize("path", GEOGRAPHIC)
def test_bbox_is_west_south_east_north(client: TestClient, service: FakeService, path: str) -> None:
    assert client.get(path, params={"bbox": "50,-10,80.5,25"}).status_code == 200
    assert service.last["geography"] == BoundingBox(
        kind="bbox", west=50.0, south=-10.0, east=80.5, north=25.0
    )


def test_bbox_may_cross_the_antimeridian(client: TestClient, service: FakeService) -> None:
    assert client.get("/v1/floats", params={"bbox": "170,-10,-170,10"}).status_code == 200
    box = service.last["geography"]
    assert isinstance(box, BoundingBox) and box.crosses_antimeridian


@pytest.mark.parametrize("path", GEOGRAPHIC)
def test_no_geography_is_none(client: TestClient, service: FakeService, path: str) -> None:
    assert client.get(path).status_code == 200
    assert service.last["geography"] is None


@pytest.mark.parametrize("path", GEOGRAPHIC)
def test_region_and_bbox_together_are_rejected(
    client: TestClient, service: FakeService, path: str
) -> None:
    response = client.get(path, params={"region": "Arabian Sea", "bbox": "50,-10,80,25"})
    error = error_of(response, 400, "invalid_parameter")
    assert [(d["field"], d["code"]) for d in error["details"]] == [
        ("geography", "invalid_geography")
    ]
    assert service.calls == []


@pytest.mark.parametrize(
    "bbox",
    ["1,2,3", "1,2,3,4,5", "a,b,c,d", ",,,", "nan,0,1,1", "200,0,10,10", "0,-91,10,10", "1;2;3;4"],
)
def test_malformed_bbox_is_rejected(client: TestClient, service: FakeService, bbox: str) -> None:
    error = error_of(client.get("/v1/floats", params={"bbox": bbox}), 400, "invalid_parameter")
    assert [(d["field"], d["code"]) for d in error["details"]] == [("bbox", "invalid_geography")]
    assert service.calls == []


@pytest.mark.parametrize("region", ["", "x" * 129])
def test_region_length_is_bounded(client: TestClient, service: FakeService, region: str) -> None:
    error = error_of(client.get("/v1/floats", params={"region": region}), 400, "invalid_parameter")
    assert error["details"][0]["field"] == "region"
    assert service.calls == []


# ----- query parameters: depth, paging, policy --------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/profiles", f"/v1/profiles/{PROFILE_ID}"])
@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, None),
        ({"depth_min": "10", "depth_max": "200"}, DepthRange(min=10.0, max=200.0)),
        ({"depth_min": "10"}, DepthRange(min=10.0, max=12000.0)),
        ({"depth_max": "200.5"}, DepthRange(min=0.0, max=200.5)),
        ({"depth_min": "0"}, DepthRange(min=0.0, max=12000.0)),
    ],
)
def test_depth_bounds_become_a_depth_range(
    client: TestClient,
    service: FakeService,
    path: str,
    params: dict[str, str],
    expected: DepthRange | None,
) -> None:
    assert client.get(path, params=params).status_code == 200
    assert service.last["depth"] == expected


@pytest.mark.parametrize("path", ["/v1/profiles", f"/v1/profiles/{PROFILE_ID}"])
@pytest.mark.parametrize(
    "params", [{"depth_min": "-1"}, {"depth_max": "0"}, {"depth_max": "12001"}]
)
def test_depth_outside_the_physical_range_is_rejected(
    client: TestClient, service: FakeService, path: str, params: dict[str, str]
) -> None:
    error = error_of(client.get(path, params=params), 400, "invalid_parameter")
    assert [(d["field"], d["code"]) for d in error["details"]] == [("depth", "invalid_depth_range")]
    assert service.calls == []


@pytest.mark.parametrize("path", ["/v1/floats", "/v1/floats/5900001", "/v1/profiles"])
def test_limit_and_cursor_are_forwarded(
    client: TestClient, service: FakeService, path: str
) -> None:
    assert client.get(path, params={"limit": "25", "cursor": "abc-_123"}).status_code == 200
    assert service.last["limit"] == 25
    assert service.last["cursor"] == "abc-_123"
    assert client.get(path).status_code == 200
    assert service.last["limit"] is None and service.last["cursor"] is None


@pytest.mark.parametrize("path", ["/v1/floats", "/v1/floats/5900001", "/v1/profiles"])
def test_cursor_length_is_bounded(client: TestClient, service: FakeService, path: str) -> None:
    assert client.get(path, params={"cursor": "c" * 512}).status_code == 200
    error = error_of(client.get(path, params={"cursor": "c" * 513}), 400, "invalid_parameter")
    assert error["details"][0]["field"] == "cursor"


def test_profiles_forwards_every_filter(client: TestClient, service: FakeService) -> None:
    response = client.get(
        "/v1/profiles",
        params={
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-02-01T00:00:00Z",
            "bbox": "60,0,70,20",
            "platform_number": "5900001",
            "depth_min": "0",
            "depth_max": "500",
            "qc_policy": "raw",
            "cursor": "next",
            "limit": "10",
        },
    )
    assert response.status_code == 200
    assert service.calls[-1][0] == "profiles"
    assert service.last == {
        "start": datetime(2025, 1, 1, tzinfo=UTC),
        "end": datetime(2025, 2, 1, tzinfo=UTC),
        "geography": BoundingBox(kind="bbox", west=60.0, south=0.0, east=70.0, north=20.0),
        "platform_number": "5900001",
        "depth": DepthRange(min=0.0, max=500.0),
        "qc_policy": "raw",
        "cursor": "next",
        "limit": 10,
    }


@pytest.mark.parametrize("path", ["/v1/profiles", f"/v1/profiles/{PROFILE_ID}"])
def test_qc_policy_defaults_to_science_ready(
    client: TestClient, service: FakeService, path: str
) -> None:
    assert client.get(path).status_code == 200
    assert service.last["qc_policy"] == "science_ready"
    assert client.get(path, params={"qc_policy": "mode_selected"}).status_code == 200
    assert service.last["qc_policy"] == "mode_selected"


def test_path_parameters_are_forwarded_verbatim(client: TestClient, service: FakeService) -> None:
    assert client.get("/v1/floats/5900001").status_code == 200
    assert service.calls[-1][:2] == ("float_detail", ("5900001",))
    assert client.get(f"/v1/profiles/{PROFILE_ID}").status_code == 200
    assert service.calls[-1][:2] == ("profile", (PROFILE_ID,))


def test_platform_number_filter_is_bounded(client: TestClient, service: FakeService) -> None:
    assert client.get("/v1/profiles", params={"platform_number": "9" * 32}).status_code == 200
    response = client.get("/v1/profiles", params={"platform_number": "9" * 33})
    assert error_of(response, 400, "invalid_parameter")["details"][0]["field"] == "platform_number"


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/v1/floats", {"limit": "abc"}, "limit"),
        ("/v1/profiles", {"limit": "1.5"}, "limit"),
        ("/v1/profiles", {"depth_min": "deep"}, "depth_min"),
        ("/v1/floats/5900001", {"limit": ""}, "limit"),
    ],
)
def test_validation_errors_are_400_invalid_parameter(
    client: TestClient, service: FakeService, path: str, params: dict[str, str], field: str
) -> None:
    error = error_of(
        client.get(path, params=params, headers={HEADER: "trace-1"}), 400, "invalid_parameter"
    )
    assert error["correlation_id"] == "trace-1"
    assert error["details"] == [
        {"field": field, "code": "invalid_value", "message": "invalid value"}
    ]
    assert service.calls == []


# ----- errors raised by the service -------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(REGISTRY))
def test_registered_errors_map_to_their_status(
    client: TestClient, service: FakeService, code: str
) -> None:
    service.failure = QueryError(code)
    response = client.get("/v1/floats", headers={HEADER: "trace-2"})
    error = error_of(response, REGISTRY[code][0], code)
    assert error["message"] == REGISTRY[code][1]
    assert error["correlation_id"] == "trace-2"
    assert response.headers[HEADER] == "trace-2"


def test_details_are_serialised_one_per_violation(client: TestClient, service: FakeService) -> None:
    service.failure = QueryError(
        "plan_invalid",
        (
            Detail("time_range", "invalid_time_range", "end must follow start"),
            Detail("variables", "unknown_variable", "unknown variable"),
        ),
    )
    error = error_of(send(client, "POST", "/v1/query"), 422, "plan_invalid")
    assert error["details"] == [
        {"field": "time_range", "code": "invalid_time_range", "message": "end must follow start"},
        {"field": "variables", "code": "unknown_variable", "message": "unknown variable"},
    ]


def test_unexpected_exception_is_an_opaque_500(client: TestClient, service: FakeService) -> None:
    secret = "SELECT password FROM app.users -- hunter2 /srv/objects/key.parquet"
    service.failure = RuntimeError(secret)
    response = client.get("/v1/floats", headers={HEADER: "trace-3"})
    error = error_of(response, 500, "internal_error")
    assert error["correlation_id"] == "trace-3"
    assert error["details"] == []
    for leaked in (secret, "hunter2", "SELECT", "RuntimeError", "Traceback", ".parquet"):
        assert leaked not in response.text


def test_unexpected_exception_without_a_header_generates_an_id(
    client: TestClient, service: FakeService
) -> None:
    service.failure = ValueError("boom")
    response = send(client, "POST", "/v1/query")
    error_of(response, 500, "internal_error")
    uuid.UUID(response.headers[HEADER])


# ----- POST /v1/query ---------------------------------------------------------------------------


def test_query_forwards_the_parsed_document(client: TestClient, service: FakeService) -> None:
    plan = {
        "dataset": "core",
        "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
        "unknown_field": {"kept": ["for", "the", "engine", "to", "reject"]},
    }
    assert client.post("/v1/query", json=plan).status_code == 200
    assert service.calls[-1][:2] == ("query", (plan,))


def test_coverage_missing_is_the_422_envelope(client: TestClient, service: FakeService) -> None:
    service.failure = QueryError("coverage_missing")
    response = send(client, "POST", "/v1/query", headers={HEADER: "trace-4"})
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "coverage_missing",
            "message": REGISTRY["coverage_missing"][1],
            "details": [],
            "correlation_id": "trace-4",
        }
    }
    assert response.headers[HEADER] == "trace-4"


def test_body_over_the_limit_is_413(client: TestClient, service: FakeService) -> None:
    limit = QueryLimits().request_bytes
    body = json.dumps({"dataset": "core", "padding": "x" * limit})
    assert len(body.encode()) > limit
    response = client.post(
        "/v1/query", content=body, headers={"Content-Type": "application/json", HEADER: "trace-5"}
    )
    error = error_of(response, 413, "payload_too_large")
    assert error["correlation_id"] == "trace-5"
    assert service.calls == []


def test_body_exactly_at_the_limit_is_accepted(client: TestClient, service: FakeService) -> None:
    limit = QueryLimits().request_bytes
    empty = json.dumps({"padding": ""})
    body = json.dumps({"padding": "x" * (limit - len(empty))})
    assert len(body.encode()) == limit
    response = client.post("/v1/query", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert len(service.calls) == 1


# query_api.py:376 declares ``body: QueryRequest``, so FastAPI parses the body first; anything that
# is not a JSON object is rejected there as 400 invalid_parameter and the handler's own checks at
# :378-385 (size limit, JSON decode -> plan_invalid) never run for it.
@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"this is not json", "application/json"),
        (b"this is not json", "text/plain"),
        (b'{"dataset": ', "application/json"),
        (b"[1, 2, 3]", "application/json"),
    ],
)
def test_non_json_object_body_is_422_plan_invalid(
    client: TestClient, service: FakeService, content: bytes, content_type: str
) -> None:
    response = client.post("/v1/query", content=content, headers={"Content-Type": content_type})
    error = error_of(response, 422, "plan_invalid")
    assert error["details"] == [
        {"field": "plan", "code": "invalid_value", "message": "JSON object required"}
    ]
    assert service.calls == []


def test_oversized_non_json_body_is_413(client: TestClient, service: FakeService) -> None:
    response = client.post(
        "/v1/query",
        content=b"x" * (QueryLimits().request_bytes + 1),
        headers={"Content-Type": "application/json"},
    )
    error_of(response, 413, "payload_too_large")
    assert service.calls == []


# ----- query service not configured -------------------------------------------------------------


@pytest.fixture
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name == "DATABASE_URL" or name.startswith("QUERY_"):
            monkeypatch.delenv(name)


def test_without_a_query_database_the_catalogue_is_503(unconfigured: None) -> None:
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get("/v1/catalog/parameters", headers={HEADER: "trace-6"})
    error = error_of(response, 503, "service_unavailable")
    assert error["correlation_id"] == "trace-6"
    assert error["details"] == []
    for method, path, _ in ENDPOINTS:
        assert send(client, method, path).status_code == 503, path


def test_settings_without_query_database_url_is_503(
    unconfigured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@localhost/unused")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "local-test")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "local-test")
    client = TestClient(create_app(), raise_server_exceptions=False)
    error_of(client.get("/v1/catalog/parameters"), 503, "service_unavailable")


def test_health_works_while_the_query_service_is_unavailable(unconfigured: None) -> None:
    async def usable() -> None:
        pass

    client = TestClient(create_app(dict.fromkeys(["database", "redis"], usable)))
    assert client.get("/v1/health/live").json() == {"status": "ok"}
    assert client.get("/v1/health/ready").status_code == 200
    error_of(client.get("/v1/catalog/parameters"), 503, "service_unavailable")
    # With no configuration at all, liveness is still up and readiness reports unavailable.
    bare = TestClient(create_app())
    assert bare.get("/v1/health/live").status_code == 200
    assert bare.get("/v1/health/ready").status_code == 503
