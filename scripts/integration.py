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
from typing import Any

from scripts.dev import (
    ROOT,
    application_commit,
    bootstrap_env,
    configuration_root,
    docker_command,
    wait_ready,
)
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


def jobs_api(api_port: int, path: str, body: dict[str, object] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{api_port}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-FloatChat-Client": "ci"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())  # type: ignore[no-any-return]


def wait_job(api_port: int, job_id: str, budget: float) -> dict[str, Any]:
    deadline = time.monotonic() + budget
    while True:
        detail = jobs_api(api_port, f"/v1/jobs/{job_id}")
        if detail["job"]["state"] in ("completed", "partial", "cancelled", "failed"):
            return detail
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} still {detail['job']['state']} after {budget}s")
        time.sleep(3)


def export_scenario(api_port: int) -> dict[str, object]:
    request = {
        "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-03-01T00:00:00Z"},
        "geography": {"kind": "named_region", "value": "Arabian Sea"},
        "depth_dbar": {"min": 0, "max": 100},
        "format": "csv",
        "idempotency_key": "ci-export-1",
    }
    created = jobs_api(api_port, "/v1/exports", request)
    assert created["created"] is True and created["job"]["state"] == "queued"
    again = jobs_api(api_port, "/v1/exports", request)
    assert again["created"] is False and again["job"]["id"] == created["job"]["id"]
    detail = wait_job(api_port, created["job"]["id"], 240)
    job = detail["job"]
    assert job["state"] == "completed", job
    assert job["progress"]["reuse_ratio"] == 1.0 and job["progress"]["fetch_total"] == 0
    data = next(a for a in detail["artefacts"] if a["role"] == "data")
    assert data["row_count"] > 0 and data["profile_count"] > 0 and data["download_url"]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{api_port}{data['download_url']}", timeout=60
    ) as response:
        payload = response.read()
        assert response.headers["X-Content-SHA256"] == data["sha256"]
    assert len(payload) == data["bytes"] and payload.startswith(b"profile_id,")
    forged = urllib.request.Request(
        f"http://127.0.0.1:{api_port}/v1/artefacts/{data['id']}/download?token=1.{'0' * 64}"
    )
    try:
        urllib.request.urlopen(forged, timeout=10)
        raise AssertionError("a forged token was accepted")
    except urllib.error.HTTPError as error:
        assert error.code == 403
    # Months before the seeded ones need a historical run; the acquire service has no key
    # and live ingestion is off, so every chunk fails and the job is partial with the gaps.
    gap = jobs_api(
        api_port,
        "/v1/exports",
        {
            **request,
            "time_range": {"start": "2024-11-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
            "idempotency_key": "ci-export-2",
        },
    )
    partial = wait_job(api_port, gap["job"]["id"], 600)
    assert partial["job"]["state"] == "partial", partial["job"]
    fetch = [c for c in partial["chunks"] if c["kind"] == "fetch"]
    assert fetch and all(c["state"] == "failed" for c in fetch), fetch
    assert {m["month"] for m in partial["job"]["result"]["missing_slots"]} >= {"2024-11", "2024-12"}
    assert any(a["role"] == "data" for a in partial["artefacts"])
    events = jobs_api(api_port, f"/v1/jobs/{gap['job']['id']}")
    assert events["job"]["progress"]["fetch_failed"] == len(fetch)
    return {
        "check": "stage5-export-job",
        "completed_job": created["job"]["id"],
        "rows": data["row_count"],
        "profiles": data["profile_count"],
        "partial_job": gap["job"]["id"],
        "failed_fetch_chunks": len(fetch),
    }


def forecast_scenario(api_port: int) -> dict[str, object]:
    created = jobs_api(
        api_port,
        "/v1/forecasts",
        {
            "variable": "temperature",
            "geography": {"kind": "named_region", "value": "Arabian Sea"},
            "depth_dbar": {"min": 0, "max": 100},
            "horizon": 3,
            "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
        },
    )
    assert created["job"]["kind"] == "forecast" and created["job"]["queue"] == "forecast"
    detail = wait_job(api_port, created["job"]["id"], 600)
    assert detail["job"]["state"] == "completed", detail["job"]
    assert detail["job"]["result"]["status"] == "refused", detail["job"]["result"]
    run = jobs_api(api_port, f"/v1/forecasts/{detail['job']['result']['forecast_run']}")
    assert run["run"]["status"] == "refused" and "history_too_short" in run["run"]["reason"]
    assert run["run"]["history"]["months"] == ["2025-01", "2025-02", "2025-03"]
    assert run["model"] is None and "not a physics-based" in run["boundary"]
    listed = jobs_api(api_port, "/v1/forecasts")["forecasts"]
    assert any(item["id"] == run["run"]["id"] for item in listed)
    return {
        "check": "stage6-forecast-job-refused-on-short-history",
        "run": run["run"]["id"],
        "reason": run["run"]["reason"],
    }


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
            COMPOSE_PROJECT_NAME=project,
            API_PORT=str(api_port),
            WEB_PORT=str(web_port),
            APPLICATION_COMMIT=application_commit(),
            # Stage 4 (ADR-0069): the disposable project opts into the rule-based provider so
            # the chat scenario runs without a key; the interpretation panel names it.
            LLM_PROVIDER="offline",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
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
            # Stage 2: the catalogue answers on an empty database; coverage reports the absence
            # of an ingestion environment as a registered error, never a stack trace.
            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/v1/catalog/parameters", timeout=10
            ) as response:
                assert response.status == 200
                assert json.loads(response.read())["plan_schema"] == "stage2-plan-v1"
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{api_port}/v1/catalog/coverage", timeout=10
                )
                raise AssertionError("coverage answered without an environment")
            except urllib.error.HTTPError as error:
                assert error.code == 422
                assert json.loads(error.read())["error"]["code"] == "coverage_missing"
            evidence.append({"check": "stage2-catalogue-on-empty-database", "passed": True})
            compose("run", "--rm", "db-init")
            # Stage 3 (ADR-0063): seed the synthetic science and catalogue so the dashboard's
            # end-to-end scenario has data; rows through the admin login, objects through the
            # API's storage credentials, no credential in any argument. A restart exercises the
            # start-up warm-up over the seeded parts.
            compose("run", "--rm", "db-init", "python", "scripts/science_seed.py", "database")
            compose("exec", "-T", "api", "python", "scripts/science_seed.py", "objects")
            compose("restart", "api")
            wait_ready(ready_url, 60)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/v1/profiles?region=Arabian%20Sea"
                "&start=2025-01-01T00:00:00Z&end=2025-02-01T00:00:00Z&depth_max=100",
                timeout=10,
            ) as response:
                listing = json.loads(response.read())
                assert listing["result"]["row_count"] == 5, listing["result"]["row_count"]
                assert listing["provenance"]["environment"]["ingested_at"]
            evidence.append({"check": "stage3-science-seed", "profiles_in_scenario": 5})
            # Stage 4 (ADR-0071, ADR-0072): embed the corpus with the offline provider, then one
            # chat message end to end: a validated plan, an executed result, the audit record.
            compose("exec", "-T", "api", "python", "scripts/semantic_seed.py")
            chat_request = urllib.request.Request(
                f"http://127.0.0.1:{api_port}/v1/chat/messages",
                data=json.dumps(
                    {
                        "text": "Monthly mean temperature in the Arabian Sea from January to "
                        "March 2025 in the upper 100 dbar"
                    }
                ).encode(),
                headers={"Content-Type": "application/json", "X-FloatChat-Client": "ci"},
                method="POST",
            )
            with urllib.request.urlopen(chat_request, timeout=60) as response:
                answer = json.loads(response.read())["message"]
                assert answer["kind"] == "answer", answer["kind"]
                audit = answer["payload"]["interpretation"]
                assert audit["provider"] == "offline" and audit["model"] == "offline-rules-v1"
                assert audit["plan"]["geography"]["value"] == "Arabian Sea"
                assert any(hit["id"].startswith("region_alias:") for hit in audit["retrieved"])
                assert answer["payload"]["result"]["result"]["row_count"] >= 1
            evidence.append({"check": "stage4-chat-offline-plan-and-execute", "passed": True})
            # Stage 5 (ADR-0079, ADR-0080): an export job over the seeded months runs through
            # the jobs worker (every slot reused, DuckDB export, signed download), and a job
            # over months the stack never fetched ends partial with the gaps listed, because
            # live ingestion is disabled here (PRD section 22, upstream unavailable).
            evidence.append(export_scenario(api_port))
            # Stage 6 (ADR-0082 to ADR-0085): a forecast request is a job on the forecast
            # queue; over the three seeded months the run is refused (history too short) with
            # its reason, and no forecast is published (PRD section 22).
            evidence.append(forecast_scenario(api_port))
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
                "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, value text); "
                "GRANT SELECT,INSERT,UPDATE,DELETE ON app.stage0_permissions TO floatchat_app; "
                "GRANT USAGE ON app.stage0_permissions_id_seq TO floatchat_app;",
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
                timeout=300,
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
