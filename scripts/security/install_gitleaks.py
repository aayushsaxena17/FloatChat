"""Download a pinned scanner into ignored local tooling, verifying upstream checksums."""

import hashlib
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.30.1"


def install(destination: Path) -> Path:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}[platform.system()]
    architecture = {"AMD64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}[
        platform.machine()
    ]
    extension = "zip" if system == "windows" else "tar.gz"
    name = f"gitleaks_{VERSION}_{system}_{architecture}.{extension}"
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/"
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / name
    urllib.request.urlretrieve(url + name, archive_path)
    with urllib.request.urlopen(url + f"gitleaks_{VERSION}_checksums.txt", timeout=30) as response:
        checksums = response.read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("scanner checksum mismatch")
    binary = "gitleaks.exe" if system == "windows" else "gitleaks"
    if system == "windows":
        with zipfile.ZipFile(archive_path) as archive:
            data = archive.read(binary)
    else:
        with tarfile.open(archive_path) as archive:
            member = archive.extractfile(binary)
            if member is None:
                raise RuntimeError("scanner binary missing")
            data = member.read()
    executable = destination / binary
    executable.write_bytes(data)
    executable.chmod(0o700)
    return executable


if __name__ == "__main__":
    install(Path(__file__).resolve().parents[2] / ".cache/tools")
    print(f"Installed checksum-verified Gitleaks {VERSION}")
