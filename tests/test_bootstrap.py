from pathlib import Path

from scripts.dev import bootstrap_env, published_port


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
