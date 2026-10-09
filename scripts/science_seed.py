"""Synthetic science seed for disposable servers and the Docker integration project (ADR-0063).

One module holds the rows the Stage 2 integration suite has always seeded (environment,
completed run, chunk, attempt, raw manifest, floats, profiles, levels, slots, parts, receipts)
and the Stage 3 additions used by the Docker project only, so the dashboard's end-to-end test
has several January 2025 Arabian Sea profiles, a trajectory and levels in 0-100 dbar. Every row
is synthetic test data, not Stage 1 evidence.

Inside the API image two entry points seed a project without a credential in any argument::

    python scripts/science_seed.py database   # DATABASE_ADMIN_URL; refuses a populated database
    python scripts/science_seed.py objects    # storage settings; verifies against the catalogue

The database step runs through the ``db-init`` service, the objects step through ``api``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

ENV = "00000000-0000-4000-8000-000000000003"
RUN = "00000000-0000-4000-8000-000000000001"
CHUNK = "00000000-0000-4000-8000-000000000002"
ATTEMPT = "00000000-0000-4000-8000-000000000004"
RAW = "00000000-0000-4000-8000-000000000005"
FLOATS = {
    "A": "00000000-0000-4000-8000-00000000000a",
    "B": "00000000-0000-4000-8000-00000000000b",
    "G": "00000000-0000-4000-8000-00000000000c",
    "C": "00000000-0000-4000-8000-00000000000d",
    "D": "00000000-0000-4000-8000-00000000000e",
}
PLATFORMS = {"A": "5900001", "B": "5900002", "G": "5900003", "C": "5900004", "D": "5900005"}
# A profile: (id, float key, platform, cycle, observed_at, lon, lat, data mode).
Profile = tuple[str, str, str, int, str, float, float, str]
# The Stage 2 rows: two argovis floats, one of them leaving the Arabian Sea for the south.
PROFILES: list[Profile] = [
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
# Stage 3 (ADR-0063): a float drifting across the Arabian Sea in January 2025 and one more
# January profile, all inside the IHO Arabian Sea polygon (checked by the integration suite).
STAGE3_PROFILES: list[Profile] = [
    (
        "00000000-0000-4000-8000-000000000301",
        "C",
        "5900004",
        10,
        "2025-01-05T06:00:00Z",
        62.0,
        14.0,
        "D",
    ),
    (
        "00000000-0000-4000-8000-000000000302",
        "C",
        "5900004",
        11,
        "2025-01-15T06:00:00Z",
        62.5,
        14.6,
        "A",
    ),
    (
        "00000000-0000-4000-8000-000000000303",
        "C",
        "5900004",
        12,
        "2025-01-25T06:00:00Z",
        63.1,
        15.1,
        "R",
    ),
    (
        "00000000-0000-4000-8000-000000000304",
        "D",
        "5900005",
        21,
        "2025-01-20T12:00:00Z",
        58.0,
        18.0,
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
UNITS = {"pressure": "dbar", "temperature": "degree_C", "salinity": "1"}


def content_hash(identifier: str) -> str:
    return hashlib.sha256(identifier.encode()).hexdigest()


def seed_sql(*, partitions_if_absent: bool = False) -> str:
    """Environment, run, chunk, attempt, raw manifest, floats and the monthly partitions."""
    create = "CREATE TABLE IF NOT EXISTS" if partitions_if_absent else "CREATE TABLE"
    floats = "\n".join(
        f"INSERT INTO app.argo_float VALUES('{FLOATS[key]}','{source}','{PLATFORMS[key]}');"
        for key, source in (("A", "argovis"), ("B", "argovis"), ("G", "gdac"))
    )
    partitions = "\n".join(
        f"{create} app.core_measurement_2025{month:02d} PARTITION OF app.core_measurement "
        f"FOR VALUES FROM ('2025-{month:02d}-01') TO ('2025-{month + 1:02d}-01');"
        for month in (1, 2, 3)
    )
    return f"""
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
{floats}
{partitions}
"""


SEED = seed_sql()
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


def extra_float_sql(profiles: Iterable[Profile]) -> str:
    """Float rows for keys the Stage 2 seed does not create (the Stage 3 floats)."""
    keys = sorted({key for _id, key, *_rest in profiles if key not in ("A", "B", "G")})
    return "\n".join(
        f"INSERT INTO app.argo_float VALUES('{FLOATS[key]}','argovis','{PLATFORMS[key]}');"
        for key in keys
    )


def profile_rows(profiles: Sequence[Profile]) -> str:
    statements = []
    for identifier, float_key, platform, cycle, observed, lon, lat, mode in profiles:
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


def part_table(identifier: str, mode: str) -> Any:
    """A Parquet part for one seeded profile in the Stage 1 schema (core-parquet-v1)."""
    import pyarrow as pa
    from floatchat_core.ingestion.parquet import schema

    columns: dict[str, list[Any]] = {field.name: [] for field in schema()}
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
            columns[variable + "_unit"].append(UNITS[variable])
            columns[variable + "_unit_source"].append(None)
            columns[variable + "_data_mode"].append(mode)
            columns[variable + "_flags"].append([])
    return pa.table(columns, schema=schema())


def parquet_bytes(identifier: str, mode: str) -> bytes:
    import pyarrow.parquet as pq

    buffer = io.BytesIO()
    pq.write_table(part_table(identifier, mode), buffer, compression="zstd")
    return buffer.getvalue()


def parts_for(profiles: Iterable[Profile]) -> dict[str, bytes]:
    return {identifier: parquet_bytes(identifier, mode) for identifier, *_r, mode in profiles}


def catalogue_rows(profiles: Sequence[Profile], parts: dict[str, bytes]) -> str:
    """One complete chunk, committed intent, slot, parts and receipt per month x tile slot."""
    from floatchat_core.ingestion.planning import GEOMETRY_SHA256

    statements = [
        f"UPDATE app.ingestion_chunk SET state='complete', completed_at=now() WHERE id='{CHUNK}';",
    ]
    by_slot: dict[str, list[tuple[str, str]]] = {}
    for identifier, _float, _platform, _cycle, observed, lon, lat, mode in profiles:
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
            f'\'{{"west":{west},"south":{south},"width":10,"height":10}}\',\'v2\',\'complete\',now());'
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


DOCKER_PROFILES: list[Profile] = PROFILES + STAGE3_PROFILES


def docker_sql(parts: dict[str, bytes]) -> list[str]:
    """The statements the Docker project's database step runs, in order."""
    return [
        seed_sql(partitions_if_absent=True),
        extra_float_sql(DOCKER_PROFILES),
        profile_rows(DOCKER_PROFILES),
        GDAC_SEED,
        catalogue_rows(DOCKER_PROFILES, parts),
    ]


class Refused(RuntimeError):
    pass


def seed_database(url: str, parts: dict[str, bytes]) -> dict[str, int]:
    """Seed through the admin login; refuse a database that already holds an environment."""
    import psycopg

    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM app.ingestion_environment")
            row = cursor.fetchone()
            if row is None or int(row[0]) != 0:
                raise Refused("the database already holds an ingestion environment; not seeded")
            for statement in docker_sql(parts):
                cursor.execute(statement)  # type: ignore[arg-type]
            cursor.execute("SELECT count(*) FROM app.argo_profile WHERE source='argovis'")
            profiles = int((cursor.fetchone() or [0])[0])
            cursor.execute("SELECT count(*) FROM app.dataset_partition WHERE status='active'")
            partitions = int((cursor.fetchone() or [0])[0])
        connection.commit()
    return {"profiles": profiles, "parts": partitions}


def seed_objects(settings: Any, parts: dict[str, bytes]) -> dict[str, int]:
    """Upload the regenerated parts after checking they are the ones the catalogue names."""
    import psycopg
    from floatchat_api.health import storage_client

    by_digest = {hashlib.sha256(payload).hexdigest(): payload for payload in parts.values()}
    url = settings.query_database_url.get_secret_value()
    with psycopg.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT object_key, sha256, bytes FROM app.query_partition")
        catalogue = cursor.fetchall()
    if not catalogue:
        raise Refused("the catalogue has no parts; run the database step first")
    client = storage_client(settings)
    uploaded = 0
    for object_key, digest, byte_count in catalogue:
        payload = by_digest.get(digest)
        if payload is None or len(payload) != int(byte_count):
            raise Refused(f"regenerated part bytes do not match the catalogue entry {digest[:12]}")
        client.put_object(Bucket=settings.object_storage_bucket, Key=object_key, Body=payload)
        body = client.get_object(Bucket=settings.object_storage_bucket, Key=object_key)["Body"]
        if hashlib.sha256(body.read()).hexdigest() != digest:
            raise Refused(f"stored object {digest[:12]} does not verify")
        uploaded += 1
    return {"objects": uploaded}


def main(argv: Sequence[str]) -> int:
    mode = argv[0] if argv else ""
    parts = parts_for(DOCKER_PROFILES)
    try:
        if mode == "database":
            url = os.environ.get("DATABASE_ADMIN_URL")
            if not url:
                raise Refused("DATABASE_ADMIN_URL is not configured")
            print(json.dumps({"seeded": seed_database(url, parts)}))
        elif mode == "objects":
            from floatchat_core.config import Settings

            settings = Settings()
            if settings.query_database_url is None:
                raise Refused("QUERY_DATABASE_URL is not configured")
            print(json.dumps({"seeded": seed_objects(settings, parts)}))
        else:
            print("usage: science_seed.py database|objects", file=sys.stderr)
            return 2
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
