from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_local_network_and_initialization_contract() -> None:
    configuration = yaml.safe_load((ROOT / "infra/docker-compose.dev.yml").read_text())
    services = configuration["services"]
    for name in ["db", "redis", "minio"]:
        assert not services[name].get("ports")
    for name in ["api", "web"]:
        assert all(port.startswith("127.0.0.1:") for port in services[name]["ports"])
    assert services["api"]["depends_on"]["db-init"]["condition"] == "service_completed_successfully"
    assert (
        services["api"]["depends_on"]["storage-init"]["condition"]
        == "service_completed_successfully"
    )
    for name in ["api", "acquire", "process", "supervisor", "jobs", "forecasts"]:
        assert "DATABASE_ADMIN_URL" not in services[name]["environment"]
        assert "MINIO_ROOT_PASSWORD" not in services[name]["environment"]
    for name in ["acquire", "process", "supervisor", "jobs", "forecasts"]:
        assert not services[name].get("ports")


def test_local_stack_runs_the_postgresql_queue_without_celery() -> None:
    # Stage 5 (ADR-0077, ADR-0078): the ingestion pool (acquire, process, supervisor) and the
    # jobs worker join the stack; the queues are PostgreSQL, there is no Celery and no broker.
    text = (ROOT / "infra/docker-compose.dev.yml").read_text()
    services = yaml.safe_load(text)["services"]
    assert "worker" not in services
    assert "celery" not in text.lower()
    assert set(services) == {
        "db",
        "redis",
        "minio",
        "db-init",
        "storage-init",
        "api",
        "web",
        "acquire",
        "process",
        "supervisor",
        "jobs",
        "forecasts",
    }
    # Only the acquire service may hold the upstream credential, and live ingestion is opt-in.
    for name in ["process", "supervisor", "jobs", "forecasts", "api", "web"]:
        assert "ARGOVIS_API_KEY" not in services[name].get("environment", {})
    assert services["acquire"]["environment"]["ARGOVIS_API_KEY"] == "${ARGOVIS_API_KEY:-}"
    assert services["acquire"]["environment"]["FLOATCHAT_LIVE_INGESTION_ENABLED"] == (
        "${FLOATCHAT_LIVE_INGESTION_ENABLED:-false}"
    )
    for name in ["process", "supervisor", "jobs", "forecasts"]:
        assert services[name]["environment"]["FLOATCHAT_LIVE_INGESTION_ENABLED"] == "false"
    assert services["forecasts"]["environment"]["JOBS_QUEUES"] == "forecast"
    for name in ["acquire", "process", "supervisor", "jobs", "forecasts"]:
        assert services[name]["command"][:2] == ["python", "scripts/dev_worker.py"]
        assert services[name]["mem_limit"]
        assert services[name]["depends_on"]["db-init"]["condition"] == (
            "service_completed_successfully"
        )
