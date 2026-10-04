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


@pytest.mark.parametrize("mode", ["current", "staged", "history", "hook"])
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
    if mode == "hook":
        import yaml

        entry = (
            f'"{Path(sys.executable).as_posix()}" '
            f'"{(ROOT / "scripts/security/scan.py").as_posix()}" '
            f'staged --scanner "{Path(scanner()).as_posix()}"'
        )
        configuration = {
            "repos": [
                {
                    "repo": "local",
                    "hooks": [
                        {
                            "id": "gitleaks-staged",
                            "name": "Gitleaks staged content",
                            "entry": entry,
                            "language": "system",
                            "pass_filenames": False,
                            "always_run": True,
                        }
                    ],
                }
            ]
        }
        (tmp_path / ".pre-commit-config.yaml").write_text(yaml.safe_dump(configuration))
        git("add", ".pre-commit-config.yaml")
        subprocess.run(
            [sys.executable, "-m", "pre_commit", "install"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        result = git("commit", "-qm", "Must be rejected", check=False)
        assert result.returncode != 0
        assert "gcp-api-key" in result.stdout + result.stderr
    else:
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
