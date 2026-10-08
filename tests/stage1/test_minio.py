"""Real local MinIO, no external network, host ports or persistent volumes."""

import os
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_P02_P03_P04_real_minio_conditional_publication_and_corrupt_final():
    image = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    client = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    for cached in (image, client):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", cached], capture_output=True, timeout=20
            ).returncode
            == 0
        ), "Prepare caches; offline tests never pull"
    name = "floatchat-stage1-minio-offline-" + uuid.uuid4().hex
    environment = dict(
        os.environ, MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--network=none",
            "--memory=512m",
            "--name",
            name,
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            image,
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
                "--memory=1g",
                "--network=container:" + name,
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/.venv/lib/python3.12/site-packages",
                client,
                "python",
                "/test/tests/stage1/minio_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, "Disposable MinIO publication verification failed"
        assert result.stdout.strip() == b"offline-minio-publication-verified"
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=True,
            capture_output=True,
            timeout=30,
        )
