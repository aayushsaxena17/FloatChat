"""Offline component proofs; synthetic HTTP is never labeled a live capture."""

import gzip
import io
import socket
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.transport import (
    RETRY_MAXIMA,
    HTTPFailure,
    empty_receipt,
    empty_receipt_request,
    public_addresses,
    read_body,
    retry_delay,
    validate_endpoint,
)


def response(data, headers=()):
    result = Mock()
    body = io.BytesIO(data)
    result.read.side_effect = body.read
    result.getheaders.return_value = list(headers)
    result.getheader.side_effect = lambda key, default=None: next(
        (value for name, value in headers if name.lower() == key.lower()), default
    )
    return result


@pytest.mark.parametrize(
    "url",
    [
        "http://argovis-api.colorado.edu/argo",
        "https://argovis-api.colorado.edu.evil.test/argo",
        "https://sentinel@argovis-api.colorado.edu/argo",
        "https://argovis-api.colorado.edu:444/argo",
        "https://argovis-api.colorado.edu/argo?key=sentinel",
        "https://argovis-api.colorado.edu/argo#x",
        "https://argovis-api.colorado.edu/arbitrary",
    ],
)
def test_B04_endpoint_allowlist(url):
    with pytest.raises(Rejection, match="unapproved_upstream_endpoint"):
        validate_endpoint(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_B04_dns_mixed_answer_rejected(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("8.8.8.8", 443)),
            (None, None, None, None, (address, 443)),
        ],
    )
    with pytest.raises(Rejection, match="upstream_dns_unsafe"):
        public_addresses()


def test_B02_gzip_stream_limits_count_unsuccessful_bytes():
    data = gzip.compress(b"a" * 10000)
    counts = []
    with pytest.raises(Rejection, match="decompressed_size_limit"):
        read_body(response(data, [("Content-Encoding", "gzip")]), counts.append, json_limit=50)
    assert sum(counts) == len(data)
    assert read_body(response(data, [("Content-Encoding", "gzip")]), lambda size: None)[0] == (
        b"a" * 10000
    )


@pytest.mark.parametrize(
    "data,headers,category",
    [
        (b"[]", [("Content-Length", "3")], "truncated_http_body"),
        (b"[]", [("Content-Length", "2"), ("Content-Length", "2")], "ambiguous_http_framing"),
        (
            b"[]",
            [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
            "ambiguous_http_framing",
        ),
        (b"[]", [("Content-Length", "-2")], "invalid_content_length"),
        (b"[]", [("Content-Encoding", "br")], "unsupported_content_encoding"),
        (gzip.compress(b"[]")[:-1], [("Content-Encoding", "gzip")], "truncated_gzip"),
        (gzip.compress(b"[]") + b"extra", [("Content-Encoding", "gzip")], "gzip_trailing_data"),
    ],
)
def test_B02_truncated_or_ambiguous_transport(data, headers, category):
    with pytest.raises(Rejection, match=category):
        read_body(response(data, headers), lambda size: None)


def test_B03_retry_policy_and_safe_exception():
    now = datetime(2025, 4, 1, tzinfo=UTC)
    # ADR-0045: equal jitter over 60/180/300 s maxima; Retry-After wins when longer.
    assert retry_delay(1, None, now, 0.5) == 45
    assert retry_delay(1, None, now, 0) == 30 and retry_delay(1, None, now, 1) == 60
    assert retry_delay(2, "30", now, 0) == 90
    assert retry_delay(1, "250", now, 0) == 250
    assert retry_delay(3, "Tue, 01 Apr 2025 00:00:05 GMT", now, 1) == 300
    assert sum(RETRY_MAXIMA.values()) == 540  # Spans a >=15 min slow episode with 4 attempts.
    for value in ("301", "NaN", "sentinel-secret", "-1", "9" * 129):
        with pytest.raises(Rejection, match="invalid_retry_after") as caught:
            retry_delay(1, value, now, 0)
        assert value not in str(caught.value)
    assert HTTPFailure(429).retryable
    assert not HTTPFailure(401).retryable
    assert str(HTTPFailure(500, "sentinel-secret")) == "upstream_http_status"


SELECTION = {
    "startDate": "2025-01-01T00:00:00Z",
    "endDate": "2025-01-08T00:00:00Z",
    "polygon": "[]",
}
LIVE_404_BODY = bytes.fromhex("5b0a0a5d0a")  # observed deployment body, reports/stage1-live-*


def test_S1_SOURCE_2_receipt_only_for_exact_selection_requests():
    assert empty_receipt_request("/argo", SELECTION)
    assert empty_receipt_request("/argo", {**SELECTION, "data": "all"})
    assert not empty_receipt_request("/argo", {"id": "6990616_100"})
    assert not empty_receipt_request("/argo", {**SELECTION, "id": "6990616_100"})
    assert not empty_receipt_request("/argo/meta", {"id": "6990616_m0"})
    assert not empty_receipt_request("/argo", {k: SELECTION[k] for k in ("startDate", "endDate")})


@pytest.mark.parametrize(
    "content_type",
    ["application/json; charset=utf-8", "application/json", "Application/JSON"],
)
def test_S1_SOURCE_2_live_shaped_404_is_empty_delivery(content_type):
    counts = []
    result = empty_receipt(
        response(LIVE_404_BODY, [("Content-Type", content_type), ("Transfer-Encoding", "chunked")]),
        counts.append,
        lambda: True,
    )
    assert result.status == 404 and result.payload == LIVE_404_BODY
    assert sum(counts) == len(LIVE_404_BODY) == result.received_bytes


@pytest.mark.parametrize(
    "data,headers",
    [
        (b'{"code":404,"message":"No documents found"}', [("Content-Type", "application/json")]),
        (b'[{"_id":"x"}]', [("Content-Type", "application/json")]),
        (b"[", [("Content-Type", "application/json")]),
        (b"", [("Content-Type", "application/json")]),
        (b"[]", [("Content-Type", "text/html")]),
        (b"[]", []),
        (b"[" + b" " * 100 + b"]", [("Content-Type", "application/json")]),
        (b"[]", [("Content-Type", "application/json"), ("Content-Length", "3")]),
        (
            gzip.compress(b"[]")[:-1],
            [("Content-Type", "application/json"), ("Content-Encoding", "gzip")],
        ),
    ],
)
def test_S1_SOURCE_2_other_404_shapes_remain_failures(data, headers):
    with pytest.raises(HTTPFailure) as caught:
        empty_receipt(response(data, headers), lambda size: None, lambda: True)
    assert caught.value.status == 404 and not caught.value.retryable


def test_S1_SOURCE_2_disabled_live_flag_wins():
    with pytest.raises(Rejection, match="live_ingestion_disabled"):
        empty_receipt(
            response(LIVE_404_BODY, [("Content-Type", "application/json")]),
            lambda size: None,
            lambda: False,
        )
