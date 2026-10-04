from pathlib import Path

import yaml


def test_local_network_and_initialization_contract() -> None:
    configuration = yaml.safe_load(Path("infra/docker-compose.dev.yml").read_text())
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
    for name in ["api", "worker"]:
        assert "DATABASE_ADMIN_URL" not in services[name]["environment"]
        assert "MINIO_ROOT_PASSWORD" not in services[name]["environment"]
