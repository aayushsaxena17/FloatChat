"""Real cgroup proof; cached image only, disabled external networking."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_F06_B01_spilled_100000_row_groups_zstd3_under_one_gib():
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    assert (
        subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=20
        ).returncode
        == 0
    )
    name = "floatchat-stage1-memory-" + uuid.uuid4().hex
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--pull=never",
                "--network=none",
                "--memory=896m",
                "--memory-swap=896m",
                "--name",
                name,
                "--user",
                str(os.getuid()),
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/.venv/lib/python3.12/site-packages",
                image,
                "python",
                "/test/tests/stage1/resource_probe.py",
            ],
            capture_output=True,
            timeout=430,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-3000:]
        evidence = json.loads(result.stdout)
        assert evidence["row_groups"] == [100000, 1]
        assert evidence["peak_rss_bytes"] < evidence["maximum_memory_budget_bytes"]
        (ROOT / "reports/stage1-parquet-resource.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=30
        )
