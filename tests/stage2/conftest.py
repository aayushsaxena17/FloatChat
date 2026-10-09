"""Stage 2 test fixtures: upstream denied; a disposable PostGIS server with migrations and seed.

The database fixture follows ``tests/stage1/test_database.py``: a pinned local image, no host
ports, no network, every migration SQL applied in order, then Stage 2 seed rows and the
``floatchat_query`` login. Offline tests never pull images.
"""

import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV = "00000000-0000-4000-8000-000000000003"
RUN = "00000000-0000-4000-8000-000000000001"
CHUNK = "00000000-0000-4000-8000-000000000002"
ATTEMPT = "00000000-0000-4000-8000-000000000004"
RAW = "00000000-0000-4000-8000-000000000005"
INTENT = "00000000-0000-4000-8000-000000000008"
FLOATS = {
    "A": "00000000-0000-4000-8000-00000000000a",
    "B": "00000000-0000-4000-8000-00000000000b",
    "G": "00000000-0000-4000-8000-00000000000c",
}
# Seeded profiles: (id, float, platform, cycle, observed_at, lon, lat, levels, data mode).
PROFILES = [
    (
        "00000000-0000-4000-8000-000000000101",
        "A",
        "5900001",
        1,
        "2025-01-10T00:00:00Z",
        65.0,
        15.0,
        "D",
    ),
    (
        "00000000-0000-4000-8000-000000000102",
        "A",
        "5900001",
        2,
        "2025-02-10T00:00:00Z",
        66.0,
        16.0,
        "A",
    ),
    (
        "00000000-0000-4000-8000-000000000103",
        "B",
        "5900002",
        7,
        "2025-01-20T00:00:00Z",
        88.0,
        15.0,
        "R",
    ),
    (
        "00000000-0000-4000-8000-000000000104",
        "B",
        "5900002",
        8,
        "2025-03-05T00:00:00Z",
        95.0,
        10.0,
        "D",
    ),
    (
        "00000000-0000-4000-8000-000000000105",
        "A",
        "5900001",
        3,
        "2025-03-15T00:00:00Z",
        75.0,
        -40.0,
        "D",
    ),
]
GDAC_PROFILE = "00000000-0000-4000-8000-000000000201"
# Levels per profile: (pressure, temperature, salinity, qc) in the delivered variant.
LEVELS = [
    (5.0, 28.0, 35.0, "1"),
    (50.0, 25.0, 35.2, "1"),
    (150.0, 15.0, 35.1, "4"),
    (400.0, 9.0, 34.9, "1"),
]
QUERY_PASSWORD = "stage2-test-query"


@pytest.fixture(autouse=True)
def deny_upstream(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Stage 2 tests deny all Python socket connections")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def _profile_rows() -> str:
    statements = []
    for identifier, float_key, platform, cycle, observed, lon, lat, mode in PROFILES:
        month = observed[:7] + "-01"
        content = json.dumps({"longitude": {"exact": str(lon)}, "latitude": {"exact": str(lat)}})
        statements.append(
            f"INSERT INTO app.argo_profile(id,source,source_profile_id,float_id,cycle_number,"
            f"direction,identity_observed_at,observation_segment,fallback_complete,observed_at,"
            f"observation_month,position,content_hash,hash_version,mapping_version,level_count,"
            f"scientific_content,created_run_id,last_scientific_run_id,last_chunk_id,"
            f"raw_manifest_id) VALUES('{identifier}','argovis','{platform}_{cycle}',"
            f"'{FLOATS[float_key]}',{cycle},'A','{observed}','single',true,'{observed}','{month}',"
            f"ST_SetSRID(ST_MakePoint({lon},{lat}),4326),'{content_hash(identifier)}',"
            f"'scientific-json-v2','argovis-core-v1',{len(LEVELS)},'{content}','{RUN}','{RUN}',"
            f"'{CHUNK}','{RAW}');"
        )
        for index, (pressure, temperature, salinity, qc) in enumerate(LEVELS):
            original = mode == "R"
            values = {
                "pressure": pressure if original else "NULL",
                "pressure_adjusted": "NULL" if original else pressure,
                "temperature": temperature if original else "NULL",
                "temperature_adjusted": "NULL" if original else temperature,
                "salinity": salinity if original else "NULL",
                "salinity_adjusted": "NULL" if original else salinity,
                "pressure_qc": f"'{qc}'" if original else "NULL",
                "pressure_adjusted_qc": "NULL" if original else f"'{qc}'",
                "temperature_qc": f"'{qc}'" if original else "NULL",
                "temperature_adjusted_qc": "NULL" if original else f"'{qc}'",
                "salinity_qc": f"'{qc}'" if original else "NULL",
                "salinity_adjusted_qc": "NULL" if original else f"'{qc}'",
            }
            statements.append(
                "INSERT INTO app.core_measurement(observation_month,profile_id,level_index,"
                + ",".join(values)
                + ",pressure_unit,temperature_unit,salinity_unit,pressure_data_mode,"
                "temperature_data_mode,salinity_data_mode,pressure_flags,temperature_flags,"
                f"salinity_flags) VALUES('{month}','{identifier}',{index},"
                + ",".join(str(v) for v in values.values())
                + f",'dbar','degree_C','1','{mode}','{mode}','{mode}','[]','[]','[]');"
            )
    return "\n".join(statements)


def content_hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode()).hexdigest()


def part_table(identifier: str, mode: str) -> pa.Table:
    """A Parquet part for one seeded profile in the Stage 1 schema (core-parquet-v1)."""
    from floatchat_core.ingestion.parquet import schema

    columns: dict[str, list] = {field.name: [] for field in schema()}
    for index, (pressure, temperature, salinity, qc) in enumerate(LEVELS):
        original = mode == "R"
        columns["profile_id"].append(identifier)
        columns["source_profile_id"].append("src")
        columns["profile_hash"].append(content_hash(identifier))
        columns["profile_content"].append("{}")
        columns["canonical_level"].append("{}")
        columns["level_index"].append(index)
        for variable, value in (
            ("pressure", pressure),
            ("temperature", temperature),
            ("salinity", salinity),
        ):
            columns[variable].append(value if original else None)
            columns[variable + "_adjusted"].append(None if original else value)
            columns[variable + "_error"].append(None)
            columns[variable + "_original_error"].append(None)
            columns[variable + "_qc"].append(qc if original else None)
            columns[variable + "_adjusted_qc"].append(None if original else qc)
            columns[variable + "_qc_source"].append(None)
            columns[variable + "_adjusted_qc_source"].append(None)
            columns[variable + "_unit"].append(
                {"pressure": "dbar", "temperature": "degree_C", "salinity": "1"}[variable]
            )
            columns[variable + "_unit_source"].append(None)
            columns[variable + "_data_mode"].append(mode)
            columns[variable + "_flags"].append([])
    return pa.table(columns, schema=schema())


def _catalogue_rows(parts: dict[str, bytes]) -> str:
    """One complete chunk, committed intent, slot, parts and receipt per month x tile slot."""
    from floatchat_core.ingestion.planning import GEOMETRY_SHA256

    statements = [
        f"UPDATE app.ingestion_chunk SET state='complete', completed_at=now() WHERE id='{CHUNK}';",
    ]
    by_slot: dict[str, list[tuple[str, str]]] = {}
    for identifier, _float, _platform, _cycle, observed, lon, lat, mode in PROFILES:
        west = int(lon // 10 * 10)
        south = int(lat // 10 * 10)
        key = (
            f"argovis/core/{observed[:7]}/{west}:{south}/indian-ocean-v1/argovis-core-v1/"
            "scientific-json-v2"
        )
        by_slot.setdefault(key, []).append((identifier, mode))
    generation = 0
    for key, members in by_slot.items():
        month = key.split("/")[2] + "-01"
        tile = key.split("/")[3]
        west, south = (int(v) for v in tile.split(":"))
        chunk = uuid.uuid5(uuid.NAMESPACE_URL, key + "/chunk")
        intent = uuid.uuid5(uuid.NAMESPACE_URL, key + "/intent")
        manifest = json.dumps(
            [{"profile_id": i, "hash": content_hash(i), "levels": len(LEVELS)} for i, _ in members]
        )
        statements.append(
            f"INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
            f"requested_end,tile,plan_version,state,completed_at) VALUES('{chunk}','{RUN}','{key}',"
            f"'{month}T00:00:00Z',('{month}'::date+interval '1 month'),"
            f"'{{\"west\":{west},\"south\":{south},\"width\":10,\"height\":10}}','v2','complete',now());"
        )
        statements.append(
            f"INSERT INTO app.publication_intent(id,chunk_id,fence,control_epoch,status,"
            f"object_references,expected_bases,expected_revisions) VALUES('{intent}','{chunk}',1,1,"
            f"'committed','[]','{{}}','{{}}');"
        )
        statements.append(
            f"INSERT INTO app.logical_partition_slot(environment_id,logical_key,observation_month,"
            f"tile_key,slot_version,membership_manifest) VALUES('{ENV}','{key}','{month}','{tile}',1,"
            f"'{manifest}');"
        )
        for identifier, _mode in members:
            generation += 1
            payload = parts[identifier]
            digest = hashlib.sha256(payload).hexdigest()
            statements.append(
                f"INSERT INTO app.dataset_partition(id,environment_id,logical_key,generation,"
                f"slot_version,status,intent_id,run_id,chunk_id,object_key,sha256,bytes,row_count,"
                f"profile_count,schema_sha256,geometry_version,geometry_sha256,versions,"
                f"membership_manifest,verified_at,verification_evidence,committed_at,kind,"
                f"part_ordinal) VALUES('{uuid.uuid5(uuid.NAMESPACE_URL, identifier)}','{ENV}','{key}',"
                f"{generation},1,'active','{intent}','{RUN}','{chunk}',"
                f"'normalised/sha256/{digest}.parquet','{digest}',{len(payload)},{len(LEVELS)},1,"
                f"'{'0' * 64}','indian-ocean-v1','{GEOMETRY_SHA256}','{{}}','[]',now(),'{{}}',now(),"
                f"'part',{generation});"
            )
        statements.append(
            f"INSERT INTO app.coverage_receipt(id,chunk_id,intent_id,environment_id,logical_key,"
            f"requested_start,requested_end,slot_version,fetch_disposition,stored_disposition,"
            f"evidence,committed_at) VALUES('{uuid.uuid5(uuid.NAMESPACE_URL, key)}','{chunk}',"
            f"'{intent}','{ENV}','{key}','{month}T00:00:00Z',('{month}'::date+interval '1 month'),1,"
            f"'profiles_returned','active_generation','{{}}',now());"
        )
    return "\n".join(statements)


SEED = f"""
INSERT INTO app.ingestion_environment VALUES('{ENV}','stage2-test','acceptance',true,'stage2','stage2','stage2');
INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,requested_start,
  requested_end,geometry_version,geometry_sha256,policy_versions,limits,controller_lease_until,
  work_deadline,deadline,state,closed)
VALUES('{RUN}','{ENV}','acceptance','2025-04-01','2025-01-01','2025-04-01','indian-ocean-v1',
       repeat('a',64),'{{}}','{{}}',now()+interval '10 minutes',now()+interval '5 hours 59 minutes',
       now()+interval '6 hours','complete',true);
INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,tile,plan_version)
VALUES('{CHUNK}','{RUN}','stage2','2025-01-01','2025-04-01',
  '{{"west":20,"south":-60,"width":10,"height":10}}','v2');
INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
  role,request_parameters) VALUES('{ATTEMPT}','{CHUNK}',1,'stage2',1,'profile','{{}}');
INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,retrieved_at,
  versions,sanitization,application_commit) VALUES('{RAW}','{RUN}','{CHUNK}','{ATTEMPT}',
  'raw/sha256/'||repeat('b',64)||'.json',repeat('b',64),2,now(),'{{}}','{{}}','stage2');
INSERT INTO app.argo_float VALUES('{FLOATS["A"]}','argovis','5900001');
INSERT INTO app.argo_float VALUES('{FLOATS["B"]}','argovis','5900002');
INSERT INTO app.argo_float VALUES('{FLOATS["G"]}','gdac','5900003');
CREATE TABLE app.core_measurement_202501 PARTITION OF app.core_measurement FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE app.core_measurement_202502 PARTITION OF app.core_measurement FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE app.core_measurement_202503 PARTITION OF app.core_measurement FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
"""
GDAC_SEED = f"""
INSERT INTO app.argo_profile(id,source,source_profile_id,float_id,cycle_number,direction,
  identity_observed_at,observation_segment,fallback_complete,observed_at,observation_month,position,
  content_hash,hash_version,mapping_version,level_count,scientific_content,created_run_id,
  last_scientific_run_id,last_chunk_id,raw_manifest_id)
VALUES('{GDAC_PROFILE}','gdac','gdac-1','{FLOATS["G"]}',1,'A','2025-01-12','single',true,
  '2025-01-12','2025-01-01',ST_SetSRID(ST_MakePoint(65.5,15.5),4326),repeat('d',64),
  'scientific-json-v2','gdac-core-v1',1,'{{}}','{RUN}','{RUN}','{CHUNK}','{RAW}');
INSERT INTO app.core_measurement(observation_month,profile_id,level_index,pressure_adjusted,
  temperature_adjusted,salinity_adjusted,pressure_adjusted_qc,temperature_adjusted_qc,
  salinity_adjusted_qc,pressure_unit,temperature_unit,salinity_unit,pressure_data_mode,
  temperature_data_mode,salinity_data_mode,pressure_flags,temperature_flags,salinity_flags)
VALUES('2025-01-01','{GDAC_PROFILE}',0,5,99,99,'1','1','1','dbar','degree_C','1','D','D','D','[]','[]','[]');
"""


class Database:
    """Handle on the disposable server: SQL as superuser plus the query login URL."""

    def __init__(self, name: str, port: int, parts: dict[str, bytes]) -> None:
        self.name = name
        self.port = port
        self.parts = parts
        self.query_url = f"postgresql://floatchat_query:{QUERY_PASSWORD}@127.0.0.1:{port}/postgres"

    def sql(self, source: str, *, expected: int = 0, timeout: int = 60) -> str:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self.name,
                "psql",
                "-X",
                "-q",
                "-t",
                "-A",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=source,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        assert result.returncode == expected, result.stderr
        # A failing statement (expected non-zero) reports its diagnostic on stderr.
        return (result.stdout if expected == 0 else result.stdout + result.stderr).strip()


@pytest.fixture(scope="session")
def database():
    image = os.environ.get("STAGE1_POSTGRES_IMAGE", "floatchat-stage0-wsl-dev-db:latest")
    assert (
        subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=20
        ).returncode
        == 0
    ), "Prepare STAGE1_POSTGRES_IMAGE separately: offline tests never pull images"
    name = "floatchat-stage2-offline-" + uuid.uuid4().hex
    # Loopback only: SQLAlchemy connects as floatchat_query through 127.0.0.1, nothing else.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--memory=1g",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:5432",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    parts = {
        identifier: _parquet_bytes(identifier, mode)
        for identifier, _f, _p, _c, _o, _lon, _lat, mode in PROFILES
    }
    handle = Database(name, port, parts)
    try:
        deadline = time.monotonic() + 60
        while True:
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                capture_output=True,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            assert time.monotonic() < deadline, "Disposable database did not become ready"
            time.sleep(0.25)
        handle.sql(
            "CREATE EXTENSION postgis; CREATE EXTENSION vector; CREATE SCHEMA app; "
            "CREATE ROLE floatchat_app NOLOGIN; CREATE ROLE floatchat_admin NOLOGIN;"
        )
        for migration in sorted((ROOT / "infra/migrations/versions").glob("*.sql")):
            handle.sql(migration.read_text(), timeout=300)
        handle.sql(SEED)
        handle.sql(_profile_rows())
        handle.sql(GDAC_SEED)
        handle.sql(_catalogue_rows(parts))
        handle.sql(
            f"ALTER ROLE floatchat_query LOGIN PASSWORD '{QUERY_PASSWORD}'; "
            "GRANT CONNECT ON DATABASE postgres TO floatchat_query;"
        )
        yield handle
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=60
        )


def _parquet_bytes(identifier: str, mode: str) -> bytes:
    import io

    buffer = io.BytesIO()
    pq.write_table(part_table(identifier, mode), buffer, compression="zstd")
    return buffer.getvalue()


@pytest.fixture
def allow_loopback(monkeypatch, database):
    """Re-enable loopback sockets for one test that talks to the disposable server."""
    monkeypatch.undo()
    yield


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
