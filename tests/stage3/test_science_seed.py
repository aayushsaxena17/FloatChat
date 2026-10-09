"""The shared seed (ADR-0063): deterministic parts, Stage 3 rows in the scenario, safe SQL."""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import science_seed as seed  # noqa: E402


def test_stage3_rows_are_january_arabian_sea_profiles_with_shallow_levels() -> None:
    assert len(seed.STAGE3_PROFILES) == 4
    for _identifier, key, platform, _cycle, observed, lon, lat, mode in seed.STAGE3_PROFILES:
        assert observed.startswith("2025-01-") and mode in ("R", "A", "D")
        # Inside the IHO Arabian Sea bbox (51.0-74.3E, -0.7-25.6N); polygon membership is
        # proven on PostGIS by the integration suite.
        assert 51.1 < lon < 74.3 and 0 < lat < 25.5
        assert key in ("C", "D") and platform == seed.PLATFORMS[key]
    assert min(level[0] for level in seed.LEVELS) < 100
    identifiers = [row[0] for row in seed.DOCKER_PROFILES]
    assert len(identifiers) == len(set(identifiers)) == 9
    cycles = {(row[1], row[3]) for row in seed.DOCKER_PROFILES}
    assert len(cycles) == 9


def test_stage2_list_is_unchanged() -> None:
    assert [row[0][-3:] for row in seed.PROFILES] == ["101", "102", "103", "104", "105"]


def test_parts_are_deterministic_and_named_by_their_digest() -> None:
    first = seed.parts_for(seed.STAGE3_PROFILES[:2])
    second = seed.parts_for(seed.STAGE3_PROFILES[:2])
    assert first == second
    rows = seed.catalogue_rows(seed.STAGE3_PROFILES[:2], first)
    for payload in first.values():
        digest = hashlib.sha256(payload).hexdigest()
        assert f"'normalised/sha256/{digest}.parquet','{digest}',{len(payload)}" in rows


def test_docker_sql_creates_partitions_only_when_absent_and_adds_the_new_floats() -> None:
    statements = seed.docker_sql(seed.parts_for(seed.DOCKER_PROFILES))
    assert statements[0].count("CREATE TABLE IF NOT EXISTS") == 3
    assert "5900004" in statements[1] and "5900005" in statements[1]
    assert "5900001" not in statements[1]  # Stage 2 floats come from the base seed
    assert seed.SEED.count("CREATE TABLE app.core_measurement_2025") == 3


def test_main_refuses_without_configuration(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    assert seed.main(["database"]) == 3
    assert "refused" in capsys.readouterr().err
    assert seed.main([]) == 2
