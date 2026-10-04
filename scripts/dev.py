"""Non-destructive local lifecycle, usable from WSL and PowerShell."""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker_command() -> str:
    executable = shutil.which("docker")
    if executable is None and os.name == "nt":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs/DockerDesktop/resources/bin/docker.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Docker/Docker/resources/bin/docker.exe",
        ]
        executable = next((str(path) for path in candidates if path.is_file()), None)
    if executable is None:
        raise RuntimeError("Docker is not available; finish Docker Desktop/WSL2 setup first.")
    # Credential helpers installed alongside Docker must be visible to this process too.
    os.environ["PATH"] = str(Path(executable).parent) + os.pathsep + os.environ.get("PATH", "")
    return executable


def configuration_root() -> Path:
    override = os.environ.get("FLOATCHAT_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/state")))
    return base / "FloatChat" / "development"


def initialize_configuration() -> None:
    from scripts.security.scan import restrict

    directory = configuration_root()
    directory.mkdir(parents=True, exist_ok=True)
    restrict(directory)
    template = directory / ".env.example"
    if not template.exists():
        shutil.copyfile(ROOT / ".env.example", template)
    bootstrap_env(directory)


def bootstrap_env(root: Path = ROOT) -> bool:
    destination = root / ".env"
    if destination.exists():
        return False
    values = (root / ".env.example").read_text()
    for name in [
        "DB_ADMIN_PASSWORD",
        "DB_APP_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "OBJECT_STORAGE_SECRET_KEY",
    ]:
        values = values.replace(f"{name}=GENERATE_LOCALLY", f"{name}={secrets.token_hex(24)}")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(values)
    return True


def compose(*args: str, timeout: int = 300) -> None:
    command = [
        docker_command(),
        "compose",
        "--env-file",
        str(configuration_root() / ".env"),
        "-f",
        str(ROOT / "infra/docker-compose.dev.yml"),
        *args,
    ]
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


def wait_ready(url: str, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                url, timeout=min(5, max(0.1, deadline - time.monotonic()))
            ) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    raise RuntimeError("Local readiness deadline exceeded; inspect local service health.")


def published_port(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        for line in (configuration_root() / ".env").read_text().splitlines():
            key, separator, candidate = line.partition("=")
            if separator and key.strip() == name:
                value = candidate.strip().strip("\"'")
    result = int(value) if value is not None else default
    if not 1 <= result <= 65535:
        raise ValueError(f"{name} must be a valid local port")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["dev", "stop", "build", "restart"])
    args = parser.parse_args()
    try:
        if args.action == "dev":
            docker_command()
            initialize_configuration()
            # Builds/downloads are prerequisites and have their own bounded budget.
            compose("build", timeout=1200)
            started = time.monotonic()
            compose("up", "-d", "--wait", "--wait-timeout", "285", timeout=290)
            wait_ready(
                f"http://127.0.0.1:{published_port('API_PORT', 8000)}/v1/health/ready",
                max(1, int(300 - (time.monotonic() - started))),
            )
            print(f"FloatChat ready: http://127.0.0.1:{published_port('WEB_PORT', 5173)}")
        elif args.action == "build":
            initialize_configuration()
            compose("build", timeout=1200)
        elif args.action == "stop":
            compose("stop")
        else:
            compose("restart", "api", "worker", "web")
            wait_ready(f"http://127.0.0.1:{published_port('API_PORT', 8000)}/v1/health/ready", 120)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Do not dump compose configuration, environment values, or service logs.
        print(
            f"Local lifecycle failed ({type(error).__name__}): {error}. No volumes were removed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
