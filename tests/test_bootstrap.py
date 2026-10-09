import re
from pathlib import Path

from scripts.bootstrap_db import STAGE1_TABLES
from scripts.dev import bootstrap_env, published_port

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_does_not_replace_configuration(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("DB_APP_PASSWORD=GENERATE_LOCALLY\n")
    assert bootstrap_env(tmp_path)
    content = (tmp_path / ".env").read_bytes()
    assert b"GENERATE_LOCALLY" not in content
    assert not bootstrap_env(tmp_path)
    assert (tmp_path / ".env").read_bytes() == content


def test_published_port_reads_preserved_configuration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLOATCHAT_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("API_PORT", raising=False)
    (tmp_path / ".env").write_text("API_PORT=18000\n")
    assert published_port("API_PORT", 8000) == 18000
    assert published_port("WEB_PORT", 5173) == 5173


def test_process_port_override_matches_compose(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLOATCHAT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("API_PORT", "28000")
    (tmp_path / ".env").write_text("API_PORT=18000\n")
    assert published_port("API_PORT", 8000) == 28000


def test_stage1_v4_tables_are_withheld_from_the_application_role() -> None:
    # Every application table created from migration 0012 on is Stage 1 ingestion state:
    # the bootstrap must revoke it from floatchat_app instead of granting blanket DML.
    created = {
        name
        for path in sorted((ROOT / "infra/migrations/versions").glob("*.sql"))
        if int(path.name[:4]) >= 12
        for name in re.findall(
            r"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+app\.(\w+)", path.read_text(), re.IGNORECASE
        )
    }
    assert {"float_metadata_cache", "measurement_staging"} <= created
    assert created <= STAGE1_TABLES
    assert {"processing_ticket", "float_metadata_cache", "measurement_staging"} <= STAGE1_TABLES
