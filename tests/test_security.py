import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def scanner() -> str:
    executable = shutil.which("gitleaks")
    if executable:
        return executable
    path = ROOT / ".cache/tools" / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
    assert path.exists(), "Pinned Gitleaks required; install before running the tests"
    return str(path)


@pytest.mark.parametrize("mode", ["current", "staged", "history"])
def test_secret_rejected_and_fully_redacted(tmp_path: Path, mode: str) -> None:
    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=check
        )

    git("init", "-q")
    git("config", "user.name", "Disposable test")
    git("config", "user.email", "test@example.invalid")
    # Synthetic test input only; assembled outside committed source.
    token = "AIza" + "aB9cD8eF7gH6iJ5kL4mN3oP2qR1sT0uVxyz"
    (tmp_path / "sample.py").write_text('api_key = "' + token + '"\n')
    git("add", "sample.py")
    if mode == "history":
        git("commit", "-qm", "Disposable scanner test")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/security/scan.py"),
            mode,
            "--source",
            str(tmp_path),
            "--scanner",
            scanner(),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["count"] >= 1
    assert token not in result.stdout + result.stderr
    assert token[:8] not in result.stdout + result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Supported non-activated Ubuntu shell contract")
def test_exact_committed_hook_without_system_python(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv, "Pinned project manager must be installed"
    project = tmp_path / "repo"
    project.mkdir()
    for name in [
        ".pre-commit-config.yaml",
        ".gitleaks.toml",
        ".gitignore",
        ".python-version",
        "pyproject.toml",
        "uv.lock",
    ]:
        shutil.copyfile(ROOT / name, project / name)
    for name in ["apps/api", "packages/core", "workers", "scripts/security"]:
        shutil.copytree(
            ROOT / name,
            project / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", ".venv"),
        )
    binary = project / ".cache/tools/gitleaks"
    binary.parent.mkdir(parents=True)
    shutil.copyfile(scanner(), binary)
    binary.chmod(0o700)
    managed_bin = tmp_path / "bin"
    managed_bin.mkdir()
    (managed_bin / "uv").symlink_to(Path(uv).resolve())
    environment = dict(os.environ, PATH=f"{managed_bin}:/usr/bin:/bin")
    for key in ["VIRTUAL_ENV", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT"]:
        environment.pop(key, None)
    assert shutil.which("python", path=environment["PATH"]) is None

    def command(*args):
        return subprocess.run(
            args, cwd=project, env=environment, capture_output=True, text=True, timeout=120
        )

    for args in [
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Disposable test"),
        ("git", "config", "user.email", "test@example.invalid"),
        ("uv", "run", "--all-packages", "--frozen", "pre-commit", "install"),
        ("git", "add", "."),
    ]:
        result = command(*args)
        assert result.returncode == 0, result.stderr
    clean = command("git", "commit", "-qm", "Clean managed-hook test")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    token = "AIza" + "aB9cD8eF7gH6iJ5kL4mN3oP2qR1sT0uVxyz"
    (project / "sample.py").write_text('api_key = "' + token + '"\n')
    assert command("git", "add", "sample.py").returncode == 0
    rejected = command("git", "commit", "-qm", "Must reject synthetic secret")
    assert rejected.returncode != 0
    assert "gcp-api-key" in rejected.stdout + rejected.stderr
    assert token not in rejected.stdout + rejected.stderr
    assert token[:8] not in rejected.stdout + rejected.stderr
    assert (project / ".pre-commit-config.yaml").read_bytes() == (
        ROOT / ".pre-commit-config.yaml"
    ).read_bytes()
