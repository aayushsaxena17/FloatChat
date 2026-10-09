"""Stage 2 integration: migration 0016, the read-only login, both execution routes, regions.

Runs against the seeded disposable PostGIS server from ``conftest.py`` (no host network beyond
loopback to that container, no upstream). Marked ``integration`` like the Stage 1 suite.
"""

import hashlib
import json
import math
from pathlib import Path

import pytest
from conftest import GDAC_PROFILE, PROFILES, utc
from floatchat_core.query.cache import PartCache
from floatchat_core.query.catalogue import QueryCatalogue, engine_from_url
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.regions import load_regions
from floatchat_core.query.router import QueryService

pytestmark = pytest.mark.integration


def _service(database, tmp_path, allow_loopback, **overrides) -> QueryService:
    limits = QueryLimits(**overrides)
    engine = engine_from_url(database.query_url, limits)

    def fetch(object_key: str, byte_count: int) -> bytes:
        digest = object_key.split("/")[-1].split(".")[0]
        for payload in database.parts.values():
            if hashlib.sha256(payload).hexdigest() == digest:
                return payload
        raise AssertionError("unknown object")

    cache = PartCache(tmp_path / "cache", 64 * 1024 * 1024, fetch)
    return QueryService(QueryCatalogue(engine, limits), limits, cache, "test")


def _plan(**overrides):
    plan = {
        "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
        "geography": {"kind": "named_region", "value": "Arabian Sea"},
        "variables": ["temperature", "salinity"],
        "qc_policy": "science_ready",
        "operation": {
            "kind": "aggregate",
            "group_by": ["month"],
            "metrics": ["mean", "count", "min", "max", "median"],
            "unit": "profile",
        },
    }
    plan.update(overrides)
    return plan


def test_migration_0016_is_idempotent_and_regions_verify(database):
    migration = (
        Path(__file__).resolve().parents[2] / "infra/migrations/versions/0016_query_access.sql"
    )
    # Views and the table already exist; a second application must fail loudly, never silently
    # recreate (additive migrations run once through alembic). The region rows use ON CONFLICT.
    database.sql(migration.read_text(), expected=3)  # psql ON_ERROR_STOP exit status
    rows = database.sql(
        "SELECT name||'|'||version||'|'||sha256||'|'||ST_IsValid(geometry)||'|'||ST_NPoints(geometry) "
        "FROM app.named_region ORDER BY name"
    ).splitlines()
    fixture = {record.name: record for record in load_regions()}
    assert len(rows) == len(fixture) == 7
    for row in rows:
        name, version, digest, valid, points = row.split("|")
        assert fixture[name].version == version
        assert fixture[name].sha256 == digest
        assert hashlib.sha256(fixture[name].wkt.encode()).hexdigest() == digest
        assert valid == "true" and int(points) == fixture[name].vertices


def test_query_login_is_read_only_and_scoped(database):
    def as_query(sql: str) -> str:
        return database.sql(f"SET ROLE floatchat_query; {sql}", expected=3)

    assert "permission denied" in as_query("SELECT count(*) FROM app.ingestion_run;")
    assert "permission denied" in as_query("SELECT count(*) FROM app.argo_profile;")
    assert "permission denied" in as_query("SELECT count(*) FROM app.raw_manifest;")
    assert "permission denied" in as_query(
        "INSERT INTO app.named_region(name,version,kind,source,citation,clipped,wkt,sha256,"
        "bbox_west,bbox_south,bbox_east,bbox_north) VALUES('x','v','iho','s','c',false,"
        "'POLYGON((0 0,1 0,1 1,0 0))',repeat('a',64),0,0,1,1);"
    )
    assert "read-only" in as_query(
        "SET default_transaction_read_only = on; BEGIN; DELETE FROM app.named_region; COMMIT;"
    )
    assert "permission denied" in as_query("COPY (SELECT 1) TO PROGRAM 'true';")
    assert "permission denied" in as_query("CREATE TABLE app.evil(x int);")
    count = database.sql("SET ROLE floatchat_query; SELECT count(*) FROM app.query_profile;")
    assert count == str(len(PROFILES) + 1)  # the gdac row is visible to the view, filtered later
    assert database.sql(
        "SET ROLE floatchat_query; SELECT count(*) FROM app.query_measurement;"
    ) == str(len(PROFILES) * 4 + 1)


def test_statement_timeout_fires_for_the_query_login(database):
    output = database.sql(
        "SET ROLE floatchat_query; SET statement_timeout = '200ms'; SELECT pg_sleep(2);",
        expected=3,
    )
    assert "canceling statement due to statement timeout" in output


def test_environment_reference_time_and_parameters(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    environment = service.catalogue.environment()
    assert environment.mode == "acceptance"
    assert environment.reference_time == utc("2025-04-01T00:00:00Z")
    assert environment.hot is not None and environment.hot.start == utc("2025-01-01T00:00:00Z")
    parameters = service.parameters()
    assert [v["name"] for v in parameters["variables"]] == ["temperature", "salinity", "pressure"]
    assert {r["name"] for r in parameters["geography"]["named_region"]} >= {
        "Arabian Sea",
        "Bay of Bengal",
        "Indian Ocean",
        "Southern Indian Ocean",
    }
    assert "wkt" not in parameters["geography"]["named_region"][0]


def test_coverage_labels_missing_slots_and_never_creates_work(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    covered = service.coverage(
        start=utc("2025-01-01T00:00:00Z"),
        end=utc("2025-02-01T00:00:00Z"),
        geography=None,
    )
    assert covered["coverage"]["slots_covered"] == 2  # tiles 60:10 and 80:10 in January
    assert covered["coverage"]["slots_missing"] == 90 - 2
    assert covered["coverage"]["partial"] is True
    runs_before = database.sql("SELECT count(*) FROM app.ingestion_run")
    chunks_before = database.sql("SELECT count(*) FROM app.ingestion_chunk")
    with pytest.raises(QueryError) as failure:
        service.query(
            _plan(
                time_range={"start": "2024-06-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
            )
        )
    assert failure.value.code == "coverage_missing"
    assert database.sql("SELECT count(*) FROM app.ingestion_run") == runs_before
    assert database.sql("SELECT count(*) FROM app.ingestion_chunk") == chunks_before


def test_profiles_region_membership_and_pagination(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    page = service.query(
        _plan(
            operation={"kind": "profiles", "limit": 2},
            geography={"kind": "named_region", "value": "Indian Ocean"},
            variables=["temperature"],
        )
    )
    assert page["execution"]["source"] == "postgresql"
    assert page["result"]["row_count"] == 2 and page["next_cursor"]
    names = [c["name"] for c in page["result"]["columns"]]
    observed = [row[names.index("observed_at")] for row in page["result"]["rows"]]
    assert observed == sorted(observed, reverse=True)
    rest = service.query(
        _plan(
            operation={"kind": "profiles", "limit": 10, "cursor": page["next_cursor"]},
            geography={"kind": "named_region", "value": "Indian Ocean"},
            variables=["temperature"],
        )
    )
    assert rest["result"]["row_count"] == len(PROFILES) - 2 and rest["next_cursor"] is None
    ids = {row[names.index("id")] for row in page["result"]["rows"] + rest["result"]["rows"]}
    assert ids == {p[0] for p in PROFILES}
    assert GDAC_PROFILE not in ids
    arabian = service.query(
        _plan(operation={"kind": "profiles", "limit": 10}, variables=["temperature"])
    )
    assert {row[names.index("platform_number")] for row in arabian["result"]["rows"]} == {"5900001"}
    assert arabian["result"]["row_count"] == 2
    southern = service.query(
        _plan(
            operation={"kind": "profiles", "limit": 10},
            geography={"kind": "named_region", "value": "Southern Indian Ocean"},
            variables=["temperature"],
        )
    )
    assert southern["result"]["row_count"] == 1
    with pytest.raises(QueryError) as failure:
        service.query(_plan(geography={"kind": "named_region", "value": "Atlantis"}))
    assert failure.value.code == "unknown_region"


def test_nearest_uses_geodesic_order_and_the_geography_index(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    response = service.query(
        _plan(
            geography={
                "kind": "point_radius",
                "longitude": 65.0,
                "latitude": 15.0,
                "radius_km": 2000,
            },
            operation={
                "kind": "nearest",
                "longitude": 65.0,
                "latitude": 15.0,
                "radius_km": 2000,
                "k": 3,
            },
            variables=["temperature"],
        )
    )
    names = [c["name"] for c in response["result"]["columns"]]
    distances = [row[names.index("distance_m")] for row in response["result"]["rows"]]
    assert distances == sorted(distances) and distances[0] == 0.0
    assert response["result"]["row_count"] == 2  # (88, 15) lies about 2,470 km away
    assert math.isclose(distances[1], 151_000, rel_tol=0.05)  # (66, 16) is about 151 km away
    plan = database.sql(
        "SET ROLE floatchat_query; EXPLAIN SELECT id FROM app.query_profile WHERE "
        "ST_DWithin(position::geography, ST_SetSRID(ST_MakePoint(65,15),4326)::geography, 3000000);"
    )
    assert "profile_position_geog" in plan


def test_aggregate_routes_agree_between_postgresql_and_duckdb(database, tmp_path, allow_loopback):
    plan = _plan(
        geography={"kind": "named_region", "value": "Indian Ocean"},
        depth_dbar={"min": 0, "max": 200},
        operation={
            "kind": "aggregate",
            "group_by": ["month", "depth_bin"],
            "metrics": ["mean", "count", "min", "max", "stddev", "median"],
            "unit": "profile",
            "depth_bin_size": 100,
        },
    )
    postgres = _service(database, tmp_path, allow_loopback).query(plan)
    assert postgres["execution"]["source"] == "postgresql"
    duck = _service(database, tmp_path, allow_loopback, postgres_level_budget=1).query(plan)
    assert duck["execution"]["source"] == "duckdb"
    assert duck["execution"]["partitions"] and duck["execution"]["members"] == len(PROFILES)
    assert [c["name"] for c in postgres["result"]["columns"]] == [
        c["name"] for c in duck["result"]["columns"]
    ]
    assert len(postgres["result"]["rows"]) == len(duck["result"]["rows"]) > 0
    for left, right in zip(postgres["result"]["rows"], duck["result"]["rows"], strict=True):
        for a, b in zip(left, right, strict=True):
            if isinstance(a, float) and isinstance(b, float):
                assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
            else:
                assert a == b
    # The science-ready policy drops the QC-4 level (150 dbar) in both engines.
    names = [c["name"] for c in postgres["result"]["columns"]]
    bins = {row[names.index("depth_bin")] for row in postgres["result"]["rows"]}
    assert bins == {0.0}
    for unit in ("measurement", "profile"):
        plan["operation"]["unit"] = unit
        plan["operation"]["group_by"] = ["month"]
        plan["operation"].pop("depth_bin_size", None)
        left = _service(database, tmp_path, allow_loopback).query(plan)["result"]["rows"]
        right = _service(database, tmp_path, allow_loopback, postgres_level_budget=1).query(plan)[
            "result"
        ]["rows"]
        assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_manifest_excludes_a_replaced_profile_on_the_duckdb_route(
    database, tmp_path, allow_loopback
):
    # Drop the first profile from its slot manifest: the part file still holds its rows, the
    # manifest says it is no longer a member, so DuckDB must not count it (contract section 7.2).
    first = PROFILES[0][0]
    key = database.sql(
        f"SELECT logical_key FROM app.logical_partition_slot WHERE membership_manifest::text LIKE '%{first}%'"
    )
    original = database.sql(
        f"SELECT membership_manifest::text FROM app.logical_partition_slot WHERE logical_key='{key}'"
    )
    reduced = json.dumps([e for e in json.loads(original) if e["profile_id"] != first])
    database.sql(
        f"UPDATE app.logical_partition_slot SET membership_manifest='{reduced}' WHERE logical_key='{key}'"
    )
    try:
        plan = _plan(
            geography={"kind": "named_region", "value": "Indian Ocean"},
            operation={
                "kind": "aggregate",
                "group_by": ["profile"],
                "metrics": ["count"],
                "unit": "measurement",
            },
            variables=["temperature"],
        )
        duck = _service(database, tmp_path, allow_loopback, postgres_level_budget=1).query(plan)
        names = [c["name"] for c in duck["result"]["columns"]]
        assert first not in {row[names.index("profile")] for row in duck["result"]["rows"]}
        assert duck["execution"]["members"] == len(PROFILES) - 1
    finally:
        database.sql(
            f"UPDATE app.logical_partition_slot SET membership_manifest='{original}' WHERE logical_key='{key}'"
        )


def test_floats_and_profile_reads(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    floats = service.floats(start=None, end=None, geography=None, cursor=None, limit=1)
    names = [c["name"] for c in floats["result"]["columns"]]
    assert floats["result"]["rows"][0][names.index("platform_number")] == "5900001"
    assert floats["result"]["rows"][0][names.index("profile_count")] == 3
    assert floats["next_cursor"]
    second = service.floats(
        start=None, end=None, geography=None, cursor=floats["next_cursor"], limit=5
    )
    assert [row[names.index("platform_number")] for row in second["result"]["rows"]] == ["5900002"]
    assert second["next_cursor"] is None
    detail = service.float_detail("5900002", start=None, end=None, cursor=None, limit=None)
    assert detail["float"]["last_cycle"] == 8 and detail["trajectory"]["row_count"] == 2
    with pytest.raises(QueryError) as missing:
        service.float_detail("5900003", start=None, end=None, cursor=None, limit=None)
    assert missing.value.code == "not_found"  # the gdac float never appears
    profile = service.profile(PROFILES[2][0], qc_policy="science_ready", depth=None)
    levels = profile["levels"]
    names = [c["name"] for c in levels["columns"]]
    temperatures = [row[names.index("temperature")] for row in levels["rows"]]
    assert temperatures == [28.0, 25.0, None, 9.0]  # R mode, QC 4 level dropped
    raw = service.profile(PROFILES[2][0], qc_policy="raw", depth=None)["levels"]
    assert "temperature_adjusted_qc" in [c["name"] for c in raw["columns"]]
    with pytest.raises(QueryError) as bad_cursor:
        service.floats(start=None, end=None, geography=None, cursor="nope", limit=None)
    assert bad_cursor.value.code == "invalid_cursor"


def test_chart_and_provenance(database, tmp_path, allow_loopback):
    service = _service(database, tmp_path, allow_loopback)
    response = service.query(
        _plan(
            geography={"kind": "named_region", "value": "Indian Ocean"},
            operation={
                "kind": "aggregate",
                "group_by": ["month"],
                "metrics": ["mean"],
                "unit": "profile",
            },
            presentation={"kind": "line_chart"},
        )
    )
    chart = response["chart"]
    assert chart["type"] == "line_chart" and chart["plotly"]["traces"][0]["type"] == "scatter"
    assert chart["encodings"]["y"]["unit"] == "degree_C"
    provenance = response["provenance"]
    assert provenance["versions"]["qc_policy"] == "qc-policy-v1/science_ready"
    assert provenance["versions"]["region"]["name"] == "Indian Ocean"
    assert provenance["environment"]["reference_time"] == "2025-04-01T00:00:00Z"
    assert provenance["result_sha256"] and provenance["execution"]["source"] == "postgresql"
    assert response["partial"] is True and response["missing"]
    ts = service.query(
        _plan(
            geography={"kind": "named_region", "value": "Indian Ocean"},
            operation={"kind": "profiles", "limit": 3},
            presentation={"kind": "ts_diagram"},
        )
    )
    assert ts["chart"]["type"] == "ts_diagram" and len(ts["chart"]["series"]) == 3
    serialized = json.dumps(response)
    for forbidden in ("normalised/", "postgresql://", "Traceback"):
        assert forbidden not in serialized
