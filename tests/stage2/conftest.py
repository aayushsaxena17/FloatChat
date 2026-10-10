"""Stage 2 test fixtures: upstream denied; a disposable PostGIS server with migrations and seed.

The database fixture follows ``tests/stage1/test_database.py``: a pinned local image, no host
ports, no network, every migration SQL applied in order, then Stage 2 seed rows and the
``floatchat_query`` login. Offline tests never pull images.
"""

import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# The seed rows and builders live in scripts/science_seed.py (ADR-0063) so the Docker
# integration project seeds the same data; the Stage 2 suite keeps the Stage 2 profile list.
from scripts.science_seed import (  # noqa: E402
    ENV,
    FLOATS,
    GDAC_PROFILE,
    GDAC_SEED,
    LEVELS,
    PROFILES,
    QUERY_PASSWORD,
    RUN,
    SEED,
    catalogue_rows,
    content_hash,
    parquet_bytes,
    part_table,
    profile_rows,
)

__all__ = [
    "ENV",
    "FLOATS",
    "GDAC_PROFILE",
    "LEVELS",
    "PROFILES",
    "RUN",
    "content_hash",
    "part_table",
]


@pytest.fixture(autouse=True)
def deny_upstream(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Stage 2 tests deny all Python socket connections")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


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
    parts = {identifier: parquet_bytes(identifier, mode) for identifier, *_r, mode in PROFILES}
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
        handle.sql(profile_rows(PROFILES))
        handle.sql(GDAC_SEED)
        handle.sql(catalogue_rows(PROFILES, parts))
        handle.sql(
            f"ALTER ROLE floatchat_query LOGIN PASSWORD '{QUERY_PASSWORD}'; "
            "GRANT CONNECT ON DATABASE postgres TO floatchat_query;"
        )
        yield handle
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=60
        )


@pytest.fixture
def allow_loopback(monkeypatch, database):
    """Re-enable loopback sockets for one test that talks to the disposable server."""
    monkeypatch.undo()
    yield


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
