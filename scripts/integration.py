"""Docker acceptance tests in a uniquely named local project. Never deletes volumes."""

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scripts.dev import ROOT, bootstrap_env, configuration_root, docker_command, wait_ready
from scripts.security.scan import restrict


def port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


@contextmanager
def integration_directory(project: str) -> Iterator[Path]:
    private = configuration_root().parent / "integration" / project
    private.mkdir(parents=True, exist_ok=False)
    restrict(private)
    # Retain configuration alongside retained volumes so failure diagnosis/recovery is possible.
    yield private


def main() -> None:
    docker = docker_command()
    project = "floatchat-stage0-test-" + uuid.uuid4().hex[:12]
    api_port, web_port = port(), port()
    evidence: list[dict[str, object]] = []
    complete = False
    with integration_directory(project) as private:
        shutil.copyfile(ROOT / ".env.example", private / ".env.example")
        bootstrap_env(private)
        configuration_keys = {
            line.split("=", 1)[0]
            for line in (private / ".env").read_text().splitlines()
            if "=" in line and not line.startswith("#")
        }
        # Ambient settings must not redirect disposable tests to cloud/production services.
        environment = {
            key: value for key, value in os.environ.items() if key not in configuration_keys
        }
        environment.update(
            COMPOSE_PROJECT_NAME=project, API_PORT=str(api_port), WEB_PORT=str(web_port)
        )
        command = [
            docker,
            "compose",
            "--env-file",
            str(private / ".env"),
            "-f",
            str(ROOT / "infra/docker-compose.dev.yml"),
        ]

        def compose(*args: str, budget: int = 300, expected: int = 0) -> None:
            print(f"Docker acceptance: {args[0]}", flush=True)
            with (private / "operations.log").open("ab") as diagnostics:
                result = subprocess.run(
                    [*command, *args],
                    cwd=ROOT,
                    env=environment,
                    stdout=diagnostics,
                    stderr=subprocess.STDOUT,
                    timeout=budget,
                )
            if result.returncode != expected:
                raise RuntimeError(
                    f"Integration {args[0]} failed (exit {result.returncode}); "
                    f"restricted diagnostics: {private / 'operations.log'}"
                )

        def probe(mode: str) -> None:
            compose("exec", "-T", "api", "python", "scripts/integration_probe.py", mode)

        ready_url = f"http://127.0.0.1:{api_port}/v1/health/ready"
        live_url = f"http://127.0.0.1:{api_port}/v1/health/live"
        try:
            compose("build", budget=1200)
            start = time.monotonic()
            compose("up", "-d", "--wait", "--wait-timeout", "290")
            wait_ready(ready_url, 5)
            assert time.monotonic() - start <= 300
            evidence.append({"check": "empty-volume-startup", "seconds": time.monotonic() - start})
            compose("run", "--rm", "db-init")
            compose(
                "run",
                "--rm",
                "db-init",
                "alembic",
                "-c",
                "infra/alembic.ini",
                "downgrade",
                "base",
                expected=1,
            )
            compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "floatchat_admin",
                "-d",
                "floatchat",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "CREATE TABLE app.stage0_persistence(value text); "
                "INSERT INTO app.stage0_persistence VALUES ('preserved'); "
                "CREATE TABLE app.stage0_permissions("
                "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, value text);",
            )
            probe("permissions")
            # Reproduce drift from the old blanket grant, then prove repeat bootstrap repairs it.
            compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "floatchat_admin",
                "-d",
                "floatchat",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "GRANT ALL ON public.spatial_ref_sys TO floatchat_app;",
            )
            compose("run", "--rm", "db-init")
            probe("permissions")
            evidence.append(
                {"check": "postgis-metadata-permissions-and-repeat-bootstrap", "passed": True}
            )
            probe("readiness-deadline")
            evidence.append(
                {"check": "hard-readiness-deadline-and-resource-disposal", "passed": True}
            )
            probe("seed")
            for dependency in ["db", "redis", "minio"]:
                compose("stop", dependency)
                try:
                    start = time.monotonic()
                    try:
                        urllib.request.urlopen(ready_url, timeout=5)
                        raise AssertionError("readiness passed during outage")
                    except urllib.error.HTTPError as error:
                        assert error.code == 503
                        assert error.read() == b'{"status":"unavailable"}'
                    assert time.monotonic() - start <= 5
                    with urllib.request.urlopen(live_url, timeout=5) as response:
                        assert response.status == 200
                finally:
                    compose("start", dependency)
                wait_ready(ready_url, 60)
                evidence.append({"check": dependency + "-outage-recovery", "passed": True})
            probe("worker")
            probe("invalid-storage")
            probe("missing-bucket")
            probe("anonymous")
            compose("stop")
            start = time.monotonic()
            compose("up", "-d", "--wait", "--wait-timeout", "110", budget=115)
            wait_ready(ready_url, 5)
            assert time.monotonic() - start <= 120
            probe("verify")
            evidence.append(
                {"check": "repeat-startup-persistence", "seconds": time.monotonic() - start}
            )
            result = subprocess.run(
                ["pnpm", "--filter", "@floatchat/web", "test:e2e"],
                cwd=ROOT,
                env=dict(environment, BASE_URL=f"http://127.0.0.1:{web_port}"),
                timeout=120,
                check=False,
                shell=os.name == "nt",
            )
            assert result.returncode == 0
            evidence.append({"check": "worker-storage-migrations-browser", "passed": True})
            complete = True
        finally:
            try:
                compose("stop")
            except (RuntimeError, subprocess.SubprocessError):
                print("Test-project stop failed; owner may need to stop retained containers.")
            Path("reports/stage0-integration.json").write_text(
                json.dumps(
                    {
                        "project": project,
                        "complete": complete,
                        "checks": evidence,
                        "volumes": "preserved",
                        "diagnostics": "Restricted local logs/configuration retained outside Git",
                    },
                    indent=2,
                )
                + "\n"
            )
            print("Disposable project stopped; volumes retained:", project)


if __name__ == "__main__":
    main()
