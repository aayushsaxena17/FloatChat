"""Separate current, index, and local reachable-history scans; never print raw findings."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {
    ".git",
    ".cache",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "coverage",
    "test-results",
    "playwright-report",
}


def restrict(directory: Path) -> None:
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami"], check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(
            [
                "icacls",
                str(directory),
                "/inheritance:r",
                "/grant:r",
                identity + ":(OI)(CI)F",
                "SYSTEM:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    else:
        directory.chmod(0o700)


def scan(mode: str, source: Path, executable: str) -> int:
    with tempfile.TemporaryDirectory(prefix="floatchat-scan-") as temporary:
        private = Path(temporary)
        restrict(private)
        export = private / "source"
        if mode == "current":
            shutil.copytree(
                source,
                export,
                ignore=lambda _path, names: [name for name in names if name in EXCLUDED],
                symlinks=True,
            )
            target = export
        elif mode == "staged":
            export.mkdir()
            subprocess.run(
                ["git", "checkout-index", "--all", "--prefix", export.as_posix() + "/"],
                cwd=source,
                check=True,
                capture_output=True,
            )
            target = export
        else:
            target = source
        report = private / "report.json"
        command = [
            executable,
            "git" if mode == "history" else "dir",
            str(target),
            "--redact=100",
            "--no-banner",
            "--max-decode-depth=3",
            "--report-format=json",
            f"--report-path={report}",
            "--config",
            str(ROOT / ".gitleaks.toml"),
        ]
        if mode == "history":
            command.append("--log-opts=--all --full-history")
        result = subprocess.run(command, capture_output=True, timeout=300)
        if result.returncode not in (0, 1):
            print("Secret scan failed to execute; no raw diagnostics emitted.", file=sys.stderr)
            return 2
        findings = json.loads(report.read_text())
        safe = [
            {
                "id": f"{mode.upper()}-{i:03d}",
                "type": item["RuleID"],
                "commit": item.get("Commit", ""),
                "path": str(item["File"]).replace(export.as_posix() + "/", ""),
                "line": item["StartLine"],
                "value": "[REDACTED]",
            }
            for i, item in enumerate(findings, 1)
        ]
        print(json.dumps({"scope": mode, "findings": safe, "count": len(safe)}))
        return result.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["current", "staged", "history"])
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--scanner")
    args = parser.parse_args()
    scanner = args.scanner or shutil.which("gitleaks")
    if scanner is None:
        path = ROOT / ".cache/tools" / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
        scanner = str(path) if path.exists() else None
    if scanner is None:
        print("Install pinned Gitleaks with scripts/security/install_gitleaks.py.", file=sys.stderr)
        raise SystemExit(2)
    try:
        raise SystemExit(scan(args.mode, args.source.resolve(), scanner))
    except (OSError, subprocess.SubprocessError):
        print("Secret scan could not complete; status is unverified.", file=sys.stderr)
        raise SystemExit(2) from None
