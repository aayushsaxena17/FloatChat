"""Migration 0015 in a real disposable PostgreSQL: gdac and argovis through the same SQL.

A gdac candidate is mapped from the committed NetCDF fixture and committed through
app.commit_publication with source 'gdac', logical key gdac/core/... and mapping
gdac-core-v1; the argovis path is committed again to prove it is unchanged. Every case ends
in ROLLBACK.
"""

import os
import secrets
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_database
from floatchat_core.ingestion import gdac
from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.numeric import CanonicalBudget
from floatchat_core.ingestion.planning import GEOMETRY_SHA256, Interval, Tile
from floatchat_core.ingestion.workflow import owner_slot, staged_candidate
from test_database import CHUNK, ENV, INTENT, PROFILE, RAW, RUN, _candidate, _literal, _publishing

postgres = test_database.postgres

ROOT = Path(__file__).resolve().parents[2]
JAN = ROOT / "tests/fixtures/gdac/20250115_prof.nc"
DAY = Interval(datetime(2025, 1, 15, tzinfo=UTC), datetime(2025, 1, 16, tzinfo=UTC))
TILE = Tile(70, -30)
RUN2 = "00000000-0000-4000-8000-0000000000b1"
CHUNK2 = "00000000-0000-4000-8000-0000000000b2"
GDAC_SLOT = "gdac/core/2025-01/70:-30/indian-ocean-v1/gdac-core-v1/scientific-json-v2"

# A second run of the seeded environment that carries the gdac policy versions and the
# one-day chunk of the fixture tile.
GDAC_SEED = f"""
INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,
  requested_start,requested_end,geometry_version,geometry_sha256,policy_versions,limits,
  controller_lease_until,work_deadline,deadline)
VALUES('{RUN2}','{ENV}','acceptance','2025-04-01','2025-01-01','2025-04-01',
       'indian-ocean-v1',repeat('a',64),{_literal(policy_versions("gdac-core-v1"))},'{{}}',
       now()+interval '10 minutes',now()+interval '5 hours 59 minutes',now()+interval '6 hours');
INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,
  tile,plan_version)
VALUES('{CHUNK2}','{RUN2}','gdac','2025-01-15','2025-01-16',
  '{{"west":70,"south":-30,"width":10,"height":10}}','v1');
"""


def gdac_profile():
    doc = next(gdac.profiles_from_netcdf(JAN, tile=TILE, interval=DAY, name="x"))
    return gdac.gdac_map_profile(doc, CanonicalBudget())


def in_gdac_run(sql):
    return sql.replace(RUN, RUN2).replace(CHUNK, CHUNK2)


def gdac_publishing(profile, candidate):
    setup, commit, _, _ = _publishing(profile, candidate, source="gdac")
    # The second run is created inside the transaction that the case rolls back.
    return in_gdac_run(setup).replace("BEGIN;", "BEGIN;" + GDAC_SEED, 1), in_gdac_run(commit)


def rejected(commit, category):
    """The commit statement as a DO block that passes only on exactly this rejection."""
    return (
        "DO $check$ BEGIN "
        + commit.replace("SELECT app.", "PERFORM app.", 1)
        + " RAISE EXCEPTION 'not_rejected'; EXCEPTION WHEN raise_exception THEN "
        + f"IF SQLERRM<>'{category}' THEN RAISE; END IF; END $check$;"
    )


@pytest.mark.integration
def test_gdac_candidate_commits_with_gdac_source_key_and_mapping(postgres):
    profile = gdac_profile()
    candidate = staged_candidate(profile, uuid.UUID(PROFILE), uuid.UUID(RAW))
    assert owner_slot(profile, "gdac") == GDAC_SLOT
    setup, commit = gdac_publishing(profile, candidate)
    result = postgres(
        setup
        + f"SELECT app.ensure_slot('{RUN2}','{CHUNK2}',1,1,'2025-01-01',70,-30);"
        + commit
        + f"""
      SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK2}';
      SELECT status FROM app.publication_intent WHERE id='{INTENT}';
      SELECT string_agg(logical_key,',') FROM app.committed_active_partitions;
      SELECT string_agg(logical_key,',') FROM app.coverage_receipt;
      SELECT source||'|'||mapping_version||'|'||level_count FROM app.argo_profile;
      SELECT source FROM app.argo_float;
      SELECT outcome||'|'||committed FROM app.profile_outcome;
      SELECT count(*) FROM app.core_measurement;
      SELECT jsonb_array_length(membership_manifest) FROM app.logical_partition_slot
        WHERE logical_key='{GDAC_SLOT}';
      SELECT app.audit_slot_manifest('{ENV}','{GDAC_SLOT}');
      SELECT accepted_profiles FROM app.ingestion_run WHERE id='{RUN2}';
      ROLLBACK;
    """
    )
    lines = [line for line in result.splitlines() if line]
    # ensure_slot answers with the gdac key of the gdac run; the commit has no result row.
    assert lines[-12] == GDAC_SLOT, lines
    assert lines[-11:] == [
        "complete",
        "committed",
        GDAC_SLOT,
        GDAC_SLOT,
        f"gdac|gdac-core-v1|{len(profile.levels)}",
        "gdac",
        "insert|true",
        str(len(profile.levels)),
        "1",
        "t",
        "1",
    ]


@pytest.mark.integration
def test_candidate_source_must_match_the_run_source(postgres, wire, linked_metadata):
    profile = gdac_profile()
    candidate = staged_candidate(profile, uuid.UUID(PROFILE), uuid.UUID(RAW))
    # A gdac candidate in the (argovis) seeded run.
    setup, commit, _, _ = _publishing(profile, candidate, source="gdac")
    postgres(setup + rejected(commit, "scientific_hash_mismatch") + "ROLLBACK;")
    # An argovis candidate in a gdac run.
    value, argovis_candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(value, argovis_candidate)
    setup = in_gdac_run(setup).replace("BEGIN;", "BEGIN;" + GDAC_SEED, 1)
    postgres(setup + rejected(in_gdac_run(commit), "scientific_hash_mismatch") + "ROLLBACK;")


@pytest.mark.integration
def test_argovis_candidate_still_commits_with_its_own_key(postgres, wire, linked_metadata):
    value, candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(value, candidate)
    result = postgres(
        setup
        + f"SELECT app.ensure_slot('{RUN}','{CHUNK}',1,1,'2025-01-01',70,10);"
        + commit
        + f"""
      SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK}';
      SELECT string_agg(logical_key,',') FROM app.committed_active_partitions;
      SELECT source||'|'||mapping_version FROM app.argo_profile;
      SELECT app.audit_slot_manifest('{ENV}',logical_key) FROM app.logical_partition_slot;
      ROLLBACK;
    """
    )
    slot = owner_slot(value)
    assert slot.startswith("argovis/core/")
    lines = [line for line in result.splitlines() if line]
    assert lines[-5:] == [slot, "complete", slot, "argovis|argovis-core-v1", "t"]


@pytest.mark.integration
def test_admission_scope_follows_the_source_of_the_policy_versions(postgres):
    def admit(request, versions):
        return (
            f"SELECT app.admit_run('{ENV}','{request}','acceptance',false,"
            "'2025-01-01','2025-02-01',"
            f"600,'{GEOMETRY_SHA256}',{_literal(versions)},'{{}}')->>'kind';"
        )

    result = postgres(
        "BEGIN;"
        + admit(uuid.uuid4(), policy_versions("gdac-core-v1"))
        + admit(uuid.uuid4(), policy_versions())
        + "SELECT string_agg(source,',' ORDER BY source) FROM app.ingestion_scope;"
        + "SELECT count(*) FROM app.ingestion_scope WHERE unfinished_run_id IS NOT NULL;"
        + "ROLLBACK;"
    )
    # Both populations are admitted at once: they are separate scopes.
    assert result.splitlines()[-4:] == ["created", "created", "argovis,gdac", "2"]


@pytest.mark.integration
def test_slot_functions_agree_with_the_python_keys(postgres):
    result = postgres(
        "SELECT app.profile_slot('gdac','2025-01-15T03:00:00Z',120,30);"
        "SELECT app.profile_slot('argovis','2025-01-15T03:00:00Z',75.5,-12.25);"
        "SELECT app.run_source('{}') || app.run_source('{\"mapping\":\"gdac-core-v1\"}');"
    )
    assert result.splitlines() == [
        "gdac/core/2025-01/110:20/indian-ocean-v1/gdac-core-v1/scientific-json-v2",
        "argovis/core/2025-01/70:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        "argovisgdac",
    ]


@pytest.mark.integration
def test_gdac_run_end_to_end_over_the_committed_fixtures(postgres):
    """A gdac run (prepare_cache over a filled cache, GdacSource, gdac_map_profile, commit)."""
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    minio = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    name = "floatchat-stage1-gdac-minio-" + uuid.uuid4().hex
    for cached in (image, minio):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", cached], capture_output=True, timeout=20
            ).returncode
            == 0
        )
    postgres("CREATE DATABASE gdac_probe")
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--memory=1g",
            "--network=container:" + postgres.container_name,
            "--mount",
            f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
            "--env",
            "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/gdac_probe",
            image,
            "alembic",
            "-c",
            "infra/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    environment = dict(
        os.environ, MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    environment.pop("ARGOVIS_API_KEY", None)
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--memory=512m",
            "--network=container:" + postgres.container_name,
            "--name",
            name,
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            minio,
            "minio",
            "server",
            "/data",
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--user",
                str(os.getuid()),
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--env",
                "HOME=/tmp/offline-stage1-home",
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/gdac_probe",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/workers/src:"
                "/test/.venv/lib/python3.12/site-packages",
                image,
                "python",
                "/test/tests/stage1/gdac_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=900,
        )
        if result.returncode != 0:
            logs = subprocess.run(
                ["docker", "logs", postgres.container_name], capture_output=True, timeout=10
            )
            errors = [line for line in logs.stderr.decode().splitlines() if "ERROR:" in line]
            raise AssertionError(str(errors[-5:]) + result.stderr.decode()[-6000:])
        assert result.stdout.splitlines()[-1] == b"offline-gdac-processor-verified"
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=True,
            capture_output=True,
            timeout=30,
        )
