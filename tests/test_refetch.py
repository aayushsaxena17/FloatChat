import hashlib
import io
from pathlib import Path

import pytest

from scripts.refetch_prototype import download


def test_atomic_success(tmp_path: Path) -> None:
    content = b"bounded test snapshot"
    output = tmp_path / "data.parquet"
    download(
        "https://example.invalid/snapshot",
        output,
        hashlib.sha256(content).hexdigest(),
        opener=lambda *_a, **_kw: io.BytesIO(content),
    )
    assert output.read_bytes() == content


@pytest.mark.parametrize("failure", ["checksum", "upstream", "timeout", "interrupted", "oversize"])
def test_failure_preserves_existing_file(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "data.parquet"
    output.write_bytes(b"existing valid file")

    class Interrupted(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise ConnectionError("interrupted")

    def open_response(*_args: object, **_kwargs: object) -> io.BytesIO:
        if failure == "upstream":
            raise OSError("upstream failed")
        if failure == "timeout":
            raise TimeoutError("bounded timeout")
        if failure == "interrupted":
            return Interrupted()
        return io.BytesIO(b"new content")

    monkeypatch.setattr("scripts.refetch_prototype.MAX_BYTES", 1 if failure == "oversize" else 100)
    with pytest.raises((ValueError, OSError)):
        download("https://example.invalid/snapshot", output, "mismatch", opener=open_response)
    assert output.read_bytes() == b"existing valid file"
    assert list(tmp_path.iterdir()) == [output]
