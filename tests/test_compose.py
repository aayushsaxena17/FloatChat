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
    for name in ["api"]:
        assert "DATABASE_ADMIN_URL" not in services[name]["environment"]
        assert "MINIO_ROOT_PASSWORD" not in services[name]["environment"]


def test_local_stack_has_no_celery_worker() -> None:
    # The Celery worker is gone; the ingestion queue is PostgreSQL and its workers
    # (acquire, process) run only where an ingestion login and environment exist.
    text = (ROOT / "infra/docker-compose.dev.yml").read_text()
    services = yaml.safe_load(text)["services"]
    assert "worker" not in services
    assert "celery" not in text.lower() and "floatchat_workers" not in text
    assert set(services) == {"db", "redis", "minio", "db-init", "storage-init", "api", "web"}
