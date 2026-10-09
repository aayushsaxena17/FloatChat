"""MinIO store protocol against a stubbed S3 client, then real local MinIO (integration)."""

import base64
import hashlib
import io
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import urllib3
from botocore.awsrequest import AWSResponse
from botocore.exceptions import EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from floatchat_core.ingestion import minio
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.objects import publish_verified

ROOT = Path(__file__).resolve().parents[2]
DATA = b"scientific-fixture"
DIGEST = hashlib.sha256(DATA).hexdigest()
ENCODED = base64.b64encode(hashlib.sha256(DATA).digest()).decode()
KEY = f"normalised/sha256/{DIGEST}.parquet"
BUCKET = "floatchat-unit-test"


def store_and_stub():
    store = MinioStore("http://127.0.0.1:9000", BUCKET, "a" * 12, "b" * 24)
    stub = Stubber(store.client)
    stub.activate()
    return store, stub


def put_params(checksum=True, data=DATA, encoded=ENCODED):
    params = {
        "Bucket": BUCKET,
        "Key": KEY,
        "Body": data,
        "ContentLength": len(data),
        "IfNoneMatch": "*",
        "ContentType": "application/octet-stream",
    }
    if checksum:
        params.update(ChecksumAlgorithm="SHA256", ChecksumSHA256=encoded)
    return params


def head_params(checksum=True):
    params = {"Bucket": BUCKET, "Key": KEY}
    if checksum:
        params["ChecksumMode"] = "ENABLED"
    return params


def head_response(size=None, encoded=ENCODED):
    response = {"ContentLength": len(DATA) if size is None else size}
    if encoded is not None:
        response["ChecksumSHA256"] = encoded
    return response


def get_response(data):
    return {"Body": StreamingBody(io.BytesIO(data), len(data)), "ContentLength": len(data)}


def refuse(stub, code, status, message="", checksum=True):
    stub.add_client_error(
        "put_object",
        service_error_code=code,
        service_message=message,
        http_status_code=status,
        expected_params=put_params(checksum),
    )


def deadline():
    return time.monotonic() + 30


def test_put_object_carries_a_server_verified_sha256_and_conditional_create():
    store = MinioStore("http://127.0.0.1:9000", BUCKET, "a" * 12, "b" * 24)
    sent = []

    def capture(request, **kwargs):
        sent.append((request.method, dict(request.headers)))
        headers = {"ETag": '"x"', "Content-Length": "0"}
        if request.method == "HEAD":
            headers = {"Content-Length": str(len(DATA)), "x-amz-checksum-sha256": ENCODED}
        raw = urllib3.response.HTTPResponse(
            body=io.BytesIO(b""),
            status=200,
            headers=headers,
            preload_content=False,
            request_method=request.method,
        )
        return AWSResponse(request.url, 200, headers, raw)

    store.client.meta.events.register("before-send.s3.*", capture)
    store.write_immutable(KEY, DATA, DIGEST, deadline())
    assert store.stat(KEY, deadline()) == {"bytes": len(DATA), "sha256": DIGEST}
    (put, put_headers), (head, head_headers) = sent
    assert put == "PUT" and head == "HEAD"
    headers = {name.lower(): value for name, value in put_headers.items()}
    assert headers["x-amz-checksum-sha256"] == ENCODED.encode()
    assert headers["x-amz-sdk-checksum-algorithm"] == b"SHA256"
    assert headers["if-none-match"] == b"*"
    # No second (CRC) checksum and no aws-chunked trailer: the one SHA-256 is the proof.
    assert not [name for name in headers if "crc" in name or "trailer" in name]
    assert {name.lower(): value for name, value in head_headers.items()}[
        "x-amz-checksum-mode"
    ] == b"ENABLED"


def test_write_immutable_is_one_put_when_the_server_verifies():
    store, stub = store_and_stub()
    stub.add_response("put_object", {}, put_params())
    store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()
    assert store.checksums is True


def test_publish_verified_is_put_and_head_and_audit_adds_get():
    store, stub = store_and_stub()
    stub.add_response("put_object", {}, put_params())
    stub.add_response("head_object", head_response(), head_params())
    evidence = publish_verified(
        store, DATA, uuid.uuid4(), lambda data: {"rows": 1}, deadline=deadline()
    )
    stub.assert_no_pending_responses()
    assert evidence.key == KEY and evidence.byte_count == len(DATA)
    stub.add_response("put_object", {}, put_params())
    stub.add_response("head_object", head_response(), head_params())
    stub.add_response("get_object", get_response(DATA), {"Bucket": BUCKET, "Key": KEY})
    publish_verified(
        store, DATA, uuid.uuid4(), lambda data: {"rows": 1}, deadline=deadline(), audit=True
    )
    stub.assert_no_pending_responses()


def test_existing_key_with_the_same_stored_checksum_is_accepted_without_a_download():
    store, stub = store_and_stub()
    refuse(stub, "PreconditionFailed", 412)
    stub.add_response("head_object", head_response(), head_params())
    store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "head",
    [
        head_response(size=len(DATA) + 1),
        head_response(encoded=base64.b64encode(b"x" * 32).decode()),
        head_response(size=len(DATA) + 1, encoded=None),
    ],
)
def test_existing_key_with_other_size_or_checksum_is_a_mismatch(head):
    store, stub = store_and_stub()
    refuse(stub, "PreconditionFailed", 412)
    stub.add_response("head_object", head, head_params())
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()  # Never an overwrite, never a repair.


@pytest.mark.parametrize("stored,category", [(DATA, None), (b"X" * len(DATA), "mismatch")])
def test_existing_key_without_a_stored_checksum_is_read_back(stored, category):
    # Same length, no checksum on the server: only the bytes themselves can tell.
    store, stub = store_and_stub()
    refuse(stub, "PreconditionFailed", 412)
    stub.add_response("head_object", head_response(encoded=None), head_params())
    stub.add_response("get_object", get_response(stored), {"Bucket": BUCKET, "Key": KEY})
    if category:
        with pytest.raises(Rejection, match="object_checksum_mismatch"):
            store.write_immutable(KEY, DATA, DIGEST, deadline())
    else:
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()


@pytest.mark.parametrize("code", sorted(minio.CHECKSUM_MISMATCH))
def test_server_checksum_mismatch_is_corruption_not_a_fallback(code):
    store, stub = store_and_stub()
    refuse(stub, code, 400)
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()
    assert store.checksums is True


@pytest.mark.parametrize(
    "code,status,message",
    [
        ("NotImplemented", 501, "A header you provided implies functionality not implemented"),
        ("InvalidRequest", 400, "The checksum algorithm is not supported"),
        ("InvalidArgument", 400, "Invalid checksum provided"),
    ],
)
def test_refused_checksum_parameters_fall_back_to_a_verified_plain_put(code, status, message):
    store, stub = store_and_stub()
    refuse(stub, code, status, message)
    stub.add_response("put_object", {}, put_params(checksum=False))
    stub.add_response("head_object", head_response(encoded=None), head_params(checksum=False))
    stub.add_response("get_object", get_response(DATA), {"Bucket": BUCKET, "Key": KEY})
    store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()
    assert store.checksums is False
    # Remembered: later writes and stats go straight to the plain requests.
    stub.add_response("put_object", {}, put_params(checksum=False))
    stub.add_response("head_object", head_response(encoded=None), head_params(checksum=False))
    stub.add_response("get_object", get_response(DATA), {"Bucket": BUCKET, "Key": KEY})
    store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "code,message",
    [
        ("InvalidRequest", "The checksum you specified does not match what we received"),
        ("InvalidArgument", "checksum mismatch"),
    ],
)
def test_a_mismatch_described_in_the_message_is_not_a_refusal(code, message):
    store, stub = store_and_stub()
    refuse(stub, code, 400, message)
    with pytest.raises(Rejection, match="object_write_failure"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()
    assert store.checksums is True


def test_fallback_read_back_rejects_wrong_stored_bytes():
    store, stub = store_and_stub()
    refuse(stub, "NotImplemented", 501)
    stub.add_response("put_object", {}, put_params(checksum=False))
    stub.add_response("head_object", head_response(encoded=None), head_params(checksum=False))
    stub.add_response("get_object", get_response(b"Y" * len(DATA)), {"Bucket": BUCKET, "Key": KEY})
    with pytest.raises(Rejection, match="object_checksum_mismatch"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())


@pytest.mark.parametrize(
    "code,status", [("InternalError", 500), ("AccessDenied", 403), ("SlowDown", 503)]
)
def test_other_server_errors_are_write_failures_without_fallback(code, status):
    store, stub = store_and_stub()
    refuse(stub, code, status)
    with pytest.raises(Rejection, match="object_write_failure"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()
    assert store.checksums is True


def test_transport_failure_is_a_write_failure(monkeypatch):
    store = MinioStore("http://127.0.0.1:9000", BUCKET, "a" * 12, "b" * 24)

    def broken(**kwargs):
        raise EndpointConnectionError(endpoint_url="http://127.0.0.1:9000")

    monkeypatch.setattr(store.client, "put_object", broken)
    with pytest.raises(Rejection, match="object_write_failure"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())


def test_write_immutable_refuses_bad_arguments(monkeypatch):
    store, stub = store_and_stub()
    with pytest.raises(Rejection, match="invalid_object_key"):
        store.write_immutable("../evil", DATA, DIGEST, deadline())
    with pytest.raises(Rejection, match="invalid_publication_key"):
        store.write_immutable(f"tmp/{'a' * 32}/{'b' * 32}", DATA, DIGEST, deadline())
    for bad in ("", "A" * 64, DIGEST[:-1], DIGEST + "0"):
        with pytest.raises(Rejection, match="invalid_object_checksum"):
            store.write_immutable(KEY, DATA, bad, deadline())
    monkeypatch.setattr(minio, "MAX_OBJECT_BYTES", len(DATA) - 1)
    with pytest.raises(Rejection, match="object_size_limit"):
        store.write_immutable(KEY, DATA, DIGEST, deadline())
    stub.assert_no_pending_responses()  # Nothing was sent.


class Dribble:
    """A body that yields one byte per read, slowly: each read alone is within any timeout."""

    def read(self, amount=None):
        time.sleep(0.03)
        return b"x"

    def close(self):
        pass


def test_read_cannot_outlast_the_operation_bound_by_dribbling():
    store, stub = store_and_stub()
    stub.add_response(
        "get_object", {"Body": Dribble(), "ContentLength": 1000}, {"Bucket": BUCKET, "Key": KEY}
    )
    started = time.monotonic()
    with pytest.raises(Rejection, match="io_deadline"):
        store.read(KEY, 1000, started + 0.2)
    assert time.monotonic() - started < 2


def test_read_folds_size_and_length_problems_but_not_the_deadline():
    store, stub = store_and_stub()
    stub.add_response("get_object", get_response(DATA), {"Bucket": BUCKET, "Key": KEY})
    assert store.read(KEY, len(DATA), deadline()) == DATA
    stub.add_response("get_object", get_response(DATA), {"Bucket": BUCKET, "Key": KEY})
    with pytest.raises(Rejection, match="object_read_failure"):
        store.read(KEY, len(DATA) - 1, deadline())
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(DATA[:-1]), len(DATA) - 1), "ContentLength": len(DATA)},
        {"Bucket": BUCKET, "Key": KEY},
    )
    with pytest.raises(Rejection, match="object_read_failure"):
        store.read(KEY, len(DATA), deadline())


def test_stat_reports_bytes_and_hex_checksum():
    store, stub = store_and_stub()
    stub.add_response("head_object", head_response(), head_params())
    assert store.stat(KEY, deadline()) == {"bytes": len(DATA), "sha256": DIGEST}
    stub.add_response("head_object", head_response(encoded=None), head_params())
    assert store.stat(KEY, deadline()) == {"bytes": len(DATA), "sha256": None}


def test_stat_failures_have_their_own_categories():
    store, stub = store_and_stub()
    stub.add_client_error("head_object", "404", http_status_code=404, expected_params=head_params())
    with pytest.raises(Rejection, match="object_missing"):
        store.stat(KEY, deadline())
    stub.add_client_error("head_object", "403", http_status_code=403, expected_params=head_params())
    with pytest.raises(Rejection, match="object_stat_failure"):
        store.stat(KEY, deadline())
    for broken in ("not base64!", base64.b64encode(b"short").decode()):
        stub.add_response("head_object", head_response(encoded=broken), head_params())
        with pytest.raises(Rejection, match="object_stat_failure"):
            store.stat(KEY, deadline())
    with pytest.raises(Rejection, match="invalid_object_key"):
        store.stat("../evil", deadline())
    stub.assert_no_pending_responses()


def test_stat_without_server_checksum_support_retries_plain_once():
    store, stub = store_and_stub()
    stub.add_client_error("head_object", "400", http_status_code=400, expected_params=head_params())
    stub.add_response("head_object", head_response(encoded=None), head_params(checksum=False))
    assert store.stat(KEY, deadline()) == {"bytes": len(DATA), "sha256": None}
    assert store.checksums is False
    stub.assert_no_pending_responses()


@pytest.mark.integration
def test_P02_P03_P04_real_minio_conditional_publication_and_corrupt_final():
    image = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    client = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    for cached in (image, client):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", cached], capture_output=True, timeout=20
            ).returncode
            == 0
        ), "Prepare caches; offline tests never pull"
    name = "floatchat-stage1-minio-offline-" + uuid.uuid4().hex
    environment = dict(
        os.environ, MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--network=none",
            "--memory=512m",
            "--name",
            name,
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            image,
            "minio",
            "server",
            "/data",
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--memory=1g",
                "--network=container:" + name,
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/.venv/lib/python3.12/site-packages",
                client,
                "python",
                "/test/tests/stage1/minio_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, "Disposable MinIO publication verification failed"
        assert result.stdout.strip() == b"offline-minio-publication-verified"
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=True,
            capture_output=True,
            timeout=30,
        )
