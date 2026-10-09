"""No live source; exact new containers and temporary data only."""

import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest
import test_database

disposable_postgres = test_database.postgres

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("STAGE1_CAPACITY_MODEL") != "1",
    reason="Long local capacity model; opt in with STAGE1_CAPACITY_MODEL=1",
)
def test_one_run_actual_270_root_plan_v2_capacity_and_pipeline_memory(disposable_postgres):
    postgres = disposable_postgres
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    minio = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    for cached in (image, minio):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", cached], capture_output=True, timeout=20
            ).returncode
            == 0
        )
    postgres("CREATE DATABASE regional_model")
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
            "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/regional_model",
            image,
            "alembic",
            "-c",
            "infra/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    environment = {k: os.environ[k] for k in os.environ if k != "ARGOVIS_API_KEY"}
    environment.update(
        MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    storage = "floatchat-stage1-regional-minio-" + uuid.uuid4().hex
    worker = "floatchat-stage1-regional-worker-" + uuid.uuid4().hex
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--memory=512m",
            "--network=container:" + postgres.container_name,
            "--name",
            storage,
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
                "--pull=never",
                "--name",
                worker,
                "--user",
                str(os.getuid()),
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--env",
                "HOME=/tmp/offline-regional-model-home",
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/regional_model",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/workers/src:"
                "/test/.venv/lib/python3.12/site-packages",
                image,
                "python",
                "/test/tests/stage1/regional_capacity_probe.py",
            ],
            env=environment,
            capture_output=True,
            # The persisted run still has its unchanged six-hour contract limit.
            # This harness allowance includes only final evidence/stop cleanup.
            timeout=21660,
        )
        assert result.returncode == 0, result.stderr.decode()
        lines = result.stdout.splitlines()
        assert lines[-1] == b"offline-regional-capacity-model-recorded"
        evidence = json.loads(lines[-2])
        assert evidence["budget_runs"] == 1 and evidence["root_chunks"] == 270
        assert evidence["cgroup_memory_limit_bytes"] == 1024**3
        assert "oom_kill 0" in evidence["cgroup_memory_events"]
        assert evidence["upstream_calls"] == evidence["credential_reads"] == 0
        (ROOT / "reports/stage1-regional-capacity-model.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
    finally:
        for created in (worker, storage):
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", created],
                check=True,
                capture_output=True,
                timeout=30,
            )
