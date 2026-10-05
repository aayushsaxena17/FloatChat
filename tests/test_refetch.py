import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.refetch_prototype import download


@dataclass
class SnapshotOpener:
    content: bytes = b"new content"
    failure: str = ""

    def __call__(self, *_args, **_kwargs):
        if self.failure == "upstream":
            raise OSError("upstream failed")
        if self.failure == "timeout":
            raise TimeoutError("bounded timeout")
        if self.failure == "interrupted":
            return Interrupted()
        return io.BytesIO(self.content)


class Interrupted(io.BytesIO):
    def read1(self, size: int = -1) -> bytes:
        raise ConnectionError("interrupted")


@dataclass
class TrustedTLSOpener:
    certificate: str

    def __call__(self, url, *, timeout):
        import ssl
        import urllib.request

        return urllib.request.urlopen(
            url, timeout=timeout, context=ssl.create_default_context(cafile=self.certificate)
        )


def test_atomic_success(tmp_path: Path) -> None:
    content = b"bounded test snapshot"
    output = tmp_path / "data.parquet"
    download(
        "https://example.invalid/snapshot",
        output,
        hashlib.sha256(content).hexdigest(),
        opener=SnapshotOpener(content),
    )
    assert output.read_bytes() == content


@pytest.mark.parametrize("failure", ["checksum", "upstream", "timeout", "interrupted", "oversize"])
def test_failure_preserves_existing_file(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "data.parquet"
    output.write_bytes(b"existing valid file")

    monkeypatch.setattr("scripts.refetch_prototype.MAX_BYTES", 1 if failure == "oversize" else 100)
    with pytest.raises((ValueError, OSError)):
        download(
            "https://example.invalid/snapshot",
            output,
            "mismatch",
            opener=SnapshotOpener(failure=failure),
        )
    assert output.read_bytes() == b"existing valid file"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("mode", ["slow-body", "delayed-eof", "slow-headers"])
def test_real_https_stream_obeys_total_deadline(tmp_path, monkeypatch, mode) -> None:
    import http.server
    import multiprocessing
    import ssl
    import subprocess
    import threading
    import time

    certificate = tmp_path / "certificate.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stop = threading.Event()
    received = threading.Event()
    body = b"bounded local TLS snapshot"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.set()
            try:
                if mode == "slow-headers":
                    for byte in b"HTTP/1.0 200 OK\r\nContent-Length: 26\r\n\r\n":
                        self.connection.sendall(bytes([byte]))
                        if stop.wait(0.04):
                            return
                    return
                self.send_response(200)
                if mode == "slow-body":
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    if mode == "slow-body" and stop.wait(0.04):
                        return
                if mode == "delayed-eof":
                    stop.wait(2)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "snapshot.parquet"
    output.write_bytes(b"existing valid snapshot")
    before_files = set(tmp_path.iterdir())
    before_children = set(multiprocessing.active_children())
    budget = 0.5
    monkeypatch.setattr("scripts.refetch_prototype.DEADLINE_SECONDS", budget)
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            download(
                f"https://localhost:{server.server_port}/snapshot",
                output,
                hashlib.sha256(body).hexdigest(),
                opener=TrustedTLSOpener(str(certificate)),
            )
        elapsed = time.monotonic() - start
        # 100 ms covers process scheduling/reaping, not a larger network deadline.
        assert elapsed <= budget + 0.1
        assert received.is_set(), "The test must reach an actual HTTPS peer"
        assert output.read_bytes() == b"existing valid snapshot"
        assert set(tmp_path.iterdir()) == before_files
        assert set(multiprocessing.active_children()) == before_children
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_plain_http_is_rejected_before_open(tmp_path) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("HTTP validation must run before the opener")

    with pytest.raises(ValueError, match="HTTPS"):
        download("http://example.invalid", tmp_path / "output", "unused", opener=forbidden)
    assert not list(tmp_path.iterdir())
