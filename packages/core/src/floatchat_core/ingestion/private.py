"""Private response preservation, never under a Git tree or Windows mount."""

import uuid
from pathlib import Path

from .numeric import Rejection


def private_directory(path: Path) -> Path:
    target = path.resolve()
    if str(target).startswith(("/mnt/", "C:")) or any(
        (parent / ".git").exists() for parent in (target, *target.parents)
    ):
        raise Rejection("unsafe_private_response_directory")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)
    return target


def preserve_original(directory: Path, attempt: uuid.UUID, payload: bytes) -> None:
    target = private_directory(directory) / (attempt.hex + ".json")
    with target.open("xb") as output:
        target.chmod(0o600)
        output.write(payload)
