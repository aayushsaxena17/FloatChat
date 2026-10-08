"""Disposable real broker stack. No ports, production volumes or upstream route."""

import json
import os
import secrets
import subprocess
import uuid

import pytest
from test_database import ROOT
from test_database import postgres as postgres_fixture

postgres = postgres_fixture

REDIS = "redis@sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952"


@pytest.mark.integration
def test_C05_C06_C07_C08_C11_P07_D01_D05_D06_B02_real_broker_process_faults(postgres):
    client = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    minio = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    for image in (client, minio, REDIS):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", image], capture_output=True, timeout=20
            ).returncode
            == 0
        ), "Prepare caches separately; never pull in offline tests"
    for database_name in ("broker_probe", "beat_probe"):
        postgres("CREATE DATABASE " + database_name)
        migration = subprocess.run(
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
                "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/" + database_name,
                client,
                "alembic",
                "-c",
                "infra/alembic.ini",
                "upgrade",
                "head",
            ],
            capture_output=True,
            timeout=60,
        )
        assert migration.returncode == 0, "Disposable broker database migration failed"
    environment = {name: os.environ[name] for name in os.environ if name != "ARGOVIS_API_KEY"}
    environment.update(
        MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    names = []
    try:
        for image, suffix, options, command in (
            (REDIS, "redis", [], ["redis-server", "--save", "", "--appendonly", "no"]),
            (
                minio,
                "minio",
                ["--env", "MINIO_ROOT_USER", "--env", "MINIO_ROOT_PASSWORD"],
                ["minio", "server", "/data"],
            ),
        ):
            name = "floatchat-stage1-broker-" + suffix + "-" + uuid.uuid4().hex
            names.append(name)
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
                    *options,
                    image,
                    *command,
                ],
                env=environment,
                capture_output=True,
                check=True,
                timeout=30,
            )
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--user",
                str(os.getuid()),
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/broker_probe",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/tests/stage1:/test/packages/core/src:/test/workers/src:/test/.venv/lib/python3.12/site-packages",
                client,
                "python",
                "/test/tests/stage1/broker_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=450,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-5000:]
        evidence = json.loads(result.stdout)
        (ROOT / "reports/stage1-broker-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        from floatchat_core.ingestion.reporting import markdown_report

        final = next(
            item["report"]
            for item in evidence["cases"]
            if item["case"] == "C08_real_deadline_expiry"
        )
        (ROOT / "reports/stage1-ingestion-example.json").write_text(
            json.dumps(final, indent=2) + "\n"
        )
        (ROOT / "reports/stage1-ingestion-example.md").write_text(markdown_report(final))
    finally:
        for name in reversed(names):
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=30
            )
