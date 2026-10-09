"""Offline tests for scripts/query_latency.py: the report generator, never the API.

The conftest denies sockets; nothing here builds a connection. The HTTP client is exercised
through a fake opener, and the report functions through synthetic rows.
"""

import io
import json
import urllib.error
from datetime import UTC, datetime

import pytest
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import validate_plan
from floatchat_core.query.regions import load_regions

from scripts import query_latency as latency
from scripts.query_latency import (
    AGGREGATE_OBJECTIVE_MS,
    METADATA_OBJECTIVE_MS,
    Call,
    Client,
    build_matrix,
    build_report,
    failure_count,
    percentile,
    render_markdown,
    summarise,
    table_verdict,
)

# ----- percentile --------------------------------------------------------------------------


def test_percentile_nearest_rank_on_small_samples():
    assert percentile([], 50) is None
    for p in (1, 50, 95, 100):
        assert percentile([7.0], p) == 7.0
    assert percentile([2.0, 1.0], 50) == 1.0  # rank ceil(0.5 * 2) = 1
    assert percentile([2.0, 1.0], 95) == 2.0  # rank ceil(0.95 * 2) = 2
    four = [40.0, 10.0, 30.0, 20.0]
    assert percentile(four, 25) == 10.0
    assert percentile(four, 50) == 20.0
    assert percentile(four, 75) == 30.0
    assert percentile(four, 95) == 40.0
    assert percentile(four, 100) == 40.0


def test_percentile_of_twenty_samples_and_purity():
    samples = [float(n) for n in range(20, 0, -1)]
    snapshot = list(samples)
    assert percentile(samples, 50) == 10.0  # rank 10
    assert percentile(samples, 95) == 19.0  # rank 19, not 20: no interpolation, no float noise
    assert percentile(samples, 100) == 20.0
    assert samples == snapshot
    assert percentile([5, 5, 5], 95) == 5


@pytest.mark.parametrize("p", [0, -1, 100.5])
def test_percentile_rejects_out_of_range(p):
    with pytest.raises(ValueError):
        percentile([1.0], p)


# ----- build_matrix ------------------------------------------------------------------------


def test_matrix_shape_and_labels():
    matrix = build_matrix()
    queries, metadata = matrix["queries"], matrix["metadata"]
    assert len(queries) == 20 and len(metadata) == 4
    groups = {"postgresql": [], "duckdb": []}
    for entry in queries:
        assert entry["group"] == entry["expected_route"] in groups
        groups[entry["group"]].append(entry)
    assert len(groups["postgresql"]) == len(groups["duckdb"]) == 10
    assert [e["kind"] for e in groups["postgresql"]].count("profiles") == 4
    assert [e["kind"] for e in groups["postgresql"]].count("nearest") == 3
    assert [e["kind"] for e in groups["postgresql"]].count("aggregate") == 3
    assert {e["kind"] for e in groups["duckdb"]} == {"aggregate"}
    labels = [e["label"] for e in queries + metadata]
    assert len(set(labels)) == 24
    assert [e["path"] for e in metadata] == [
        "/v1/catalog/parameters",
        "/v1/catalog/coverage?region=Arabian%20Sea",
        "/v1/floats?limit=100",
        "/v1/profiles?region=Arabian%20Sea&limit=100",
    ]
    assert {e["method"] for e in metadata} == {"GET"} and {e["group"] for e in metadata} == {
        "metadata"
    }


def test_every_plan_validates_and_stays_in_the_data_window():
    limits = QueryLimits()
    regions = {record.name for record in load_regions()}
    for entry in build_matrix()["queries"]:
        plan = entry["plan"]
        validated = validate_plan(json.loads(json.dumps(plan)), limits)
        assert validated.operation.kind == entry["kind"], entry["label"]
        assert validated.presentation.kind == "table"
        assert validated.qc_policy == "science_ready"
        start, end = validated.time_range.start, validated.time_range.end
        assert datetime(2025, 1, 1, tzinfo=UTC) <= start < end <= datetime(2025, 4, 1, tzinfo=UTC)
        assert plan["time_range"]["start"].endswith("Z") and plan["time_range"]["end"].endswith("Z")
        if plan["geography"]["kind"] == "named_region":
            # validate_plan does not resolve names; the service answers unknown_region at runtime.
            assert plan["geography"]["value"] in regions, entry["label"]
        assert len(json.dumps(plan)) < limits.request_bytes


def test_postgresql_group_follows_plan_section_9():
    plans = [e for e in build_matrix()["queries"] if e["group"] == "postgresql"]
    for entry in plans:
        plan, operation = entry["plan"], entry["plan"]["operation"]
        if entry["kind"] == "profiles":
            assert operation["limit"] == 100
        elif entry["kind"] == "nearest":
            geography = plan["geography"]
            assert geography["kind"] == "point_radius"
            assert (geography["longitude"], geography["latitude"], geography["radius_km"]) == (
                operation["longitude"],
                operation["latitude"],
                operation["radius_km"],
            )
            assert 10 <= operation["k"] <= 100
        else:
            assert operation["group_by"] == ["month"] and operation["unit"] == "profile"
            start = datetime.fromisoformat(plan["time_range"]["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(plan["time_range"]["end"].replace("Z", "+00:00"))
            assert (end - start).days <= 31
    assert {e["plan"]["geography"]["kind"] for e in plans} >= {"named_region", "bbox"}
    assert any("depth_dbar" in e["plan"] for e in plans if e["kind"] == "profiles")
    assert {e["kind"] for e in plans if e["plan"]["geography"]["kind"] == "bbox"} >= {"aggregate"}
    nearest_k = sorted(e["plan"]["operation"]["k"] for e in plans if e["kind"] == "nearest")
    assert nearest_k[0] == 10 and nearest_k[-1] == 100


def test_duckdb_group_follows_plan_section_9():
    plans = [e["plan"] for e in build_matrix()["queries"] if e["group"] == "duckdb"]
    operations = [plan["operation"] for plan in plans]
    assert {op["kind"] for op in operations} == {"aggregate"}
    assert {op["unit"] for op in operations} == {"profile", "measurement"}
    assert {op.get("depth_bin_size") for op in operations} == {None, 50, 100}
    assert {tuple(op["group_by"]) for op in operations} == {
        ("month",),
        ("month", "depth_bin"),
        ("month", "float"),
    }
    assert all(
        tuple(op["metrics"]) == ("mean", "count", "min", "max", "median") for op in operations
    )
    assert all(
        plan["geography"] == {"kind": "named_region", "value": "Indian Ocean"} for plan in plans
    )
    spans = [(p["time_range"]["start"], p["time_range"]["end"]) for p in plans]
    assert ("2025-01-01T00:00:00Z", "2025-04-01T00:00:00Z") in spans  # the whole quarter
    assert max(spans, key=lambda s: s[1])[1] == "2025-04-01T00:00:00Z"


# ----- summarise and verdicts --------------------------------------------------------------


def ok_call(wall_ms, *, source="postgresql", server_ms=5.0, rows=3, levels=1000, partial=False):
    body = {
        "execution": {"source": source, "elapsed_ms": server_ms},
        "result": {"row_count": rows},
        "coverage": {"estimated_levels": levels},
        "partial": partial,
    }
    return Call(200, wall_ms, body)


def failed_call(code="plan_invalid", status=422):
    return Call(status, 3.0, {"error": {"code": code}}, code)


ENTRY = {
    "label": "P08 aggregate",
    "group": "postgresql",
    "kind": "aggregate",
    "expected_route": "postgresql",
    "plan": {},
}


def test_summarise_computes_statistics_from_the_samples():
    warm = [ok_call(float(n), server_ms=float(n) / 2) for n in range(1, 21)]
    row = summarise(ENTRY, ok_call(99.0), warm)
    assert row["status"] == "ok" and row["route_ok"] and row["actual_route"] == "postgresql"
    assert row["cold_ms"] == 99.0
    assert (row["warm_p50_ms"], row["warm_p95_ms"]) == (10.0, 19.0)
    assert (row["server_p50_ms"], row["server_p95_ms"]) == (5.0, 9.5)
    assert row["estimated_levels"] == 1000 and row["rows"] == 3 and row["partial"] is False
    assert len(row["warm_ms"]) == len(row["server_ms"]) == 20


def test_summarise_marks_a_route_mismatch_and_a_failed_call():
    row = summarise(ENTRY, ok_call(10.0, source="duckdb"), [ok_call(5.0, source="duckdb")])
    assert row["status"] == "ok" and not row["route_ok"] and row["actual_route"] == "duckdb"
    mixed = summarise(ENTRY, ok_call(10.0), [ok_call(5.0, source="duckdb")])
    assert mixed["actual_route"] == "duckdb+postgresql" and not mixed["route_ok"]
    failed = summarise(ENTRY, ok_call(10.0), [ok_call(4.0), failed_call("statement_timeout", 504)])
    assert failed["status"] == "statement_timeout" and failed["http_status"] == 504
    assert failed["failed_calls"] == 1 and failed["warm_ms"] == [4.0]
    cold_failed = summarise(ENTRY, failed_call("cost_over_budget"), [])
    assert cold_failed["cold_ms"] is None and cold_failed["warm_p95_ms"] is None
    assert cold_failed["actual_route"] is None and cold_failed["error_codes"] == [
        "cost_over_budget"
    ]


def test_warm_loop_discards_warmup_and_stops_at_a_failure():
    calls = iter([ok_call(float(n)) for n in range(1, 8)])
    recorded = latency._warm(lambda: next(calls), ok_call(1.0), warmup=2, runs=3)
    assert [c.wall_ms for c in recorded] == [3.0, 4.0, 5.0]
    sequence = iter([ok_call(1.0), failed_call(), ok_call(9.0)])
    stopped = latency._warm(lambda: next(sequence), ok_call(1.0), warmup=2, runs=3)
    assert len(stopped) == 1 and not stopped[0].ok
    assert latency._warm(lambda: pytest.fail("no warm calls"), failed_call(), 2, 3) == []


def row(label, p95, *, group="postgresql", status="ok", route_ok=True, expected="postgresql"):
    return {
        "label": label,
        "group": group,
        "kind": "aggregate" if expected else "metadata",
        "status": status,
        "http_status": 200 if status == "ok" else 422,
        "expected_route": expected,
        "actual_route": expected if route_ok else "duckdb",
        "route_ok": route_ok,
        "estimated_levels": 12345,
        "rows": 7,
        "partial": False,
        "cold_ms": (p95 or 0) + 100.0,
        "warm_p50_ms": None if p95 is None else p95 / 2,
        "warm_p95_ms": p95,
        "server_p50_ms": None if p95 is None else p95 / 4,
        "server_p95_ms": None if p95 is None else p95 / 3,
    }


def meta_row(label, p95):
    base = row(label, p95, group="metadata", expected=None)
    base.update(estimated_levels=None, rows=None, server_p50_ms=None, server_p95_ms=None)
    return base


META = {
    "date": "2026-10-09",
    "git_head": "abcdef012345",
    "git_dirty": False,
    "base_url": "http://127.0.0.1:8000",
    "runs": 20,
    "warmup": 2,
    "restart_command": "make restart",
    "host": "Linux-test-host",
    "cpu_count": 4,
    "dataset": {"session": "0123456789abcdef", "digest": "d" * 64},
    "limits": {"postgres_level_budget": 1000000, "duckdb_level_budget": 5000000},
}


def test_table_verdict_is_strictly_under_the_objective():
    table = {"objective_ms": 2000.0, "rows": [meta_row("a", 1999.9), meta_row("b", 12.0)]}
    verdict = table_verdict(table)
    assert verdict["pass"] and verdict["worst_warm_p95_ms"] == 1999.9 and not verdict["problems"]
    table["rows"].append(meta_row("c", 2000.0))
    verdict = table_verdict(table)
    assert (
        not verdict["pass"] and "c: warm p95 2000.0 ms is not under 2000 ms" in verdict["problems"]
    )
    assert not table_verdict({"objective_ms": 1.0, "rows": []})["pass"]


def test_render_markdown_tables_header_and_passing_verdicts():
    report = build_report(
        META,
        [
            row("P01 profiles", 120.0),
            row("D01 aggregate", 4999.0, group="duckdb", expected="duckdb"),
        ],
        [meta_row("GET /v1/floats?limit=100", 80.0)],
    )
    assert report["failures"] == 0
    text = render_markdown(report)
    assert text.count("| route | plan | est. levels | rows | cold ms |") == 3
    for needle in (
        "# Stage 2 query latency report, 2026-10-09",
        "`abcdef012345`",
        "http://127.0.0.1:8000",
        "Linux-test-host, 4 CPUs",
        "0123456789abcdef",
        "d" * 64,
        "postgres_level_budget=1000000",
        "| postgresql | P01 profiles | 12,345 | 7 | 220.0 | 60.0 | 120.0 | 30.0 | 40.0 | ok |",
        "| duckdb | D01 aggregate |",
        "| metadata | GET /v1/floats?limit=100 | - | - |",
        "Worst warm p95: 4999.0 ms. **PASS**",
        "warm p95 under 2000 ms",
        "warm p95 under 5000 ms",
    ):
        assert needle in text, needle
    assert "FAIL" not in text
    assert text.count("**PASS**") == 3 and text.count("| PASS |") == 3


def test_render_markdown_fails_each_table_on_its_own_objective():
    # 2500 ms is over the metadata objective but under the aggregate one; 5000 ms fails both.
    report = build_report(
        META,
        [row("P01", 2500.0), row("D01", 5000.0, group="duckdb", expected="duckdb")],
        [meta_row("GET /v1/profiles", 2500.0)],
    )
    verdicts = {t["id"]: t["verdict"]["pass"] for t in report["tables"]}
    assert verdicts == {"postgresql": True, "duckdb": False, "metadata": False}
    text = render_markdown(report)
    assert text.count("**FAIL**") == 2 and text.count("**PASS**") == 1
    assert "D01: warm p95 5000.0 ms is not under 5000 ms" in text
    assert "GET /v1/profiles: warm p95 2500.0 ms is not under 2000 ms" in text
    assert report["failures"] == 0  # slow is a verdict, not a failed request


def test_route_mismatch_and_errors_are_marked_and_counted():
    report = build_report(
        META,
        [
            row("P01", 10.0, route_ok=False, expected="postgresql"),
            row("P02", None, status="plan_invalid"),
        ],
        [meta_row("GET /v1/floats?limit=100", 80.0)],
    )
    assert failure_count(report) == 2 and report["failures"] == 2
    text = render_markdown(report)
    assert "**duckdb** (expected postgresql)" in text
    assert "**route mismatch**" in text
    assert "**plan_invalid** HTTP 422" in text
    assert "P01: ran on duckdb, expected postgresql" in text
    assert "P02: failed with plan_invalid" in text
    assert "| FAIL |" in text


def test_report_is_json_serialisable_and_contains_only_measured_rows():
    report = build_report(META, [row("P01", 1.0)], [meta_row("GET /v1/floats?limit=100", 2.0)])
    round_trip = json.loads(json.dumps(report))
    assert [t["id"] for t in round_trip["tables"]] == ["postgresql", "duckdb", "metadata"]
    assert round_trip["tables"][1]["rows"] == []
    assert round_trip["kind"] == "stage2_query_latency"


# ----- client, with a fake opener ----------------------------------------------------------


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return FakeResponse(self.outcome)  # a fresh body for every request


def client_with(outcome):
    client = Client("http://127.0.0.1:8000/")
    client._opener = FakeOpener(outcome)
    return client


def test_client_sends_the_correlation_header_and_a_60_second_timeout():
    client = client_with(b'{"execution": {"source": "postgresql"}}')
    first = client.query({"dataset": "core"})
    second = client.request("GET", "/v1/floats?limit=100")
    assert first.ok and first.status == 200 and second.ok
    (post, timeout), (get, _) = client._opener.requests
    assert timeout == 60.0
    assert post.full_url == "http://127.0.0.1:8000/v1/query" and post.get_method() == "POST"
    assert json.loads(post.data) == {"dataset": "core"}
    assert post.get_header("X-correlation-id") == "latency-1"
    assert post.get_header("Content-type") == "application/json"
    assert get.get_method() == "GET" and get.data is None
    assert get.get_header("X-correlation-id") == "latency-2"


def test_client_reads_the_error_envelope_code():
    envelope = json.dumps({"error": {"code": "cost_over_budget", "message": "m", "details": []}})
    failure = urllib.error.HTTPError(
        "http://x/v1/query", 422, "Unprocessable", {}, io.BytesIO(envelope.encode())
    )
    call = client_with(failure).query({})
    assert (call.ok, call.status, call.error) == (False, 422, "cost_over_budget")
    bare = urllib.error.HTTPError("http://x/v1/query", 502, "Bad", {}, io.BytesIO(b"<html>"))
    assert client_with(bare).query({}).error == "http_502"


def test_client_classifies_transport_failures_and_bad_bodies():
    assert client_with(TimeoutError()).query({}).error == "timeout"
    assert client_with(urllib.error.URLError(TimeoutError())).query({}).error == "timeout"
    assert client_with(urllib.error.URLError(ConnectionRefusedError())).query({}).error == (
        "connection_error"
    )
    assert client_with(b"not json").query({}).error == "invalid_response"
    assert client_with(b"[1, 2]").query({}).error == "invalid_response"


# ----- command line ------------------------------------------------------------------------


def test_defaults_and_validation(capsys):
    before = datetime.now(UTC).strftime("%Y-%m-%d")
    args = latency.parse_args([])
    assert (args.base_url, args.runs, args.warmup) == ("http://127.0.0.1:8000", 20, 2)
    assert (
        str(args.out) == "reports" and args.dataset_report is None and args.restart_command is None
    )
    assert args.date in {before, datetime.now(UTC).strftime("%Y-%m-%d")}  # tolerate a midnight
    for bad in (
        ["--runs", "0"],
        ["--warmup", "-1"],
        ["--date", "2026-13-01"],
        ["--base-url", "file:///x"],
    ):
        with pytest.raises(SystemExit):
            latency.parse_args(bad)
    capsys.readouterr()


def test_dataset_report_session_and_digest_are_copied(tmp_path):
    path = tmp_path / "stage2-dataset-0123456789abcdef.json"
    path.write_text(
        json.dumps(
            {
                "session": "0123456789abcdef",
                "dump_sha256": "e" * 64,
                "row_counts": {"argo_profile": 5814, "core_measurement": 4144346},
            }
        )
    )
    assert latency.load_dataset_report(path) == {
        "session": "0123456789abcdef",
        "digest": "e" * 64,
        "report": path.name,
        "profiles": 5814,
        "levels": 4144346,
    }
    path.write_text("{}")
    with pytest.raises(latency.Failure):
        latency.load_dataset_report(path)
    with pytest.raises(latency.Failure):
        latency.load_dataset_report(tmp_path / "missing.json")


def test_write_outputs_names_files_by_date(tmp_path):
    report = build_report(META, [row("P01", 1.0)], [meta_row("GET /v1/floats?limit=100", 2.0)])
    json_path, markdown_path = latency.write_outputs(report, tmp_path / "nested" / "reports")
    assert json_path.name == "query_latency_2026-10-09.json"
    assert markdown_path.name == "query_latency_2026-10-09.md"
    assert json.loads(json_path.read_text())["git_head"] == "abcdef012345"
    assert markdown_path.read_text().startswith("# Stage 2 query latency report")


def test_objectives_match_prd_section_3_1():
    assert METADATA_OBJECTIVE_MS == 2000.0 and AGGREGATE_OBJECTIVE_MS == 5000.0


# ----- orchestration, with a fake client (no sockets) --------------------------------------


class FakeApi:
    """Stands in for Client: answers from the plan's shape, counts calls, never connects."""

    mismatch = False
    instances: list["FakeApi"] = []

    def __init__(self, base_url):
        self.base_url = base_url
        self.calls = 0
        FakeApi.instances.append(self)

    def query(self, plan):
        self.calls += 1
        whole = plan["geography"].get("value") == "Indian Ocean"
        route = "duckdb" if plan["operation"]["kind"] == "aggregate" and whole else "postgresql"
        if self.mismatch and route == "duckdb":
            route = "postgresql"
        return ok_call(10.0 + self.calls, source=route, levels=2_000_000 if whole else 5_000)

    def request(self, method, path, document=None, *, correlation=None):
        self.calls += 1
        if path == "/v1/catalog/parameters":
            return Call(200, 4.0, {"limits": {"nearest_k": 100}})
        return Call(200, 4.0 + self.calls, {"result": {"row_count": 100}})


@pytest.fixture
def fake_api(monkeypatch):
    FakeApi.mismatch = False
    FakeApi.instances = []
    monkeypatch.setattr(latency, "Client", FakeApi)
    monkeypatch.setattr(latency, "git_state", lambda: ("abcdef012345", False))
    return FakeApi


def run_main(tmp_path, *extra):
    return latency.main(
        ["--runs", "3", "--warmup", "1", "--out", str(tmp_path), "--date", "2026-10-09", *extra]
    )


def test_main_measures_every_plan_and_writes_both_files(fake_api, tmp_path, capsys):
    assert run_main(tmp_path, "--restart-command", "true") == 0
    report = json.loads((tmp_path / "query_latency_2026-10-09.json").read_text())
    assert [(t["id"], len(t["rows"])) for t in report["tables"]] == [
        ("postgresql", 10),
        ("duckdb", 10),
        ("metadata", 4),
    ]
    assert report["limits"] == {"nearest_k": 100} and report["restart_command"] == "true"
    assert report["failures"] == 0 and all(t["verdict"]["pass"] for t in report["tables"])
    for table in report["tables"]:
        for measured in table["rows"]:
            assert len(measured["warm_ms"]) == 3 and measured["cold_ms"] is not None
    duckdb_rows = report["tables"][1]["rows"]
    assert {r["actual_route"] for r in duckdb_rows} == {"duckdb"}
    # one liveness poll after the restart, 24 cold calls, 24 * (1 warm-up + 3 runs)
    assert fake_api.instances[0].calls == 1 + 24 + 24 * 4
    markdown = (tmp_path / "query_latency_2026-10-09.md").read_text()
    assert "nearest_k=100" in markdown and markdown.count("**PASS**") == 3
    capsys.readouterr()


def test_main_exits_2_after_writing_files_on_a_route_mismatch(fake_api, tmp_path, capsys):
    fake_api.mismatch = True
    assert run_main(tmp_path) == 2
    report = json.loads((tmp_path / "query_latency_2026-10-09.json").read_text())
    assert report["failures"] == 10
    text = (tmp_path / "query_latency_2026-10-09.md").read_text()
    assert text.count("**postgresql** (expected duckdb)") == 10
    assert "10 row(s) failed" in capsys.readouterr().err


def test_main_exits_1_when_the_restart_command_fails(fake_api, tmp_path, capsys):
    assert run_main(tmp_path, "--restart-command", "false") == 1
    assert not list(tmp_path.glob("query_latency_*"))
    assert "restart command exited with status 1" in capsys.readouterr().err
