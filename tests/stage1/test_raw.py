from decimal import Decimal
from urllib.parse import quote

import pytest
from floatchat_core.ingestion.numeric import Rejection, decode_json
from floatchat_core.ingestion.raw import sanitize_raw


def test_B04_B05_raw_urls_and_fields_never_retain_credential():
    sentinel = "synthetic-private-marker"
    raw = (
        b'{"source":{"url":"https://user:synthetic-private-marker@official.test/a?'
        b'key=synthetic-private-marker#fragment"},"api_key":"synthetic-private-marker",'
        b'"value":0.1000000000000000001}'
    )
    result = sanitize_raw(raw, sentinel)
    assert sentinel.encode() not in result.payload
    assert decode_json(result.payload)["value"] == Decimal("0.1000000000000000001")
    assert decode_json(result.payload)["source"]["url"] == "https://official.test/a"
    assert result.manifest == {
        "version": "raw-sanitization-v1",
        "credential_fields_removed": 1,
        "urls_scrubbed": 1,
    }
    assert sentinel not in str(result.manifest)


def test_N01_raw_sanitization_preserves_written_numeric_token_bounds():
    # Rewriting this to exponent-free text would violate the 128-byte source
    # token cap, even though its original token and canonical text are valid.
    token = "0." + "1" * 100 + "e-400"
    raw = ('{"value":' + token + "}").encode()
    result = sanitize_raw(raw)
    assert result.payload == raw
    assert decode_json(result.payload)["value"] == decode_json(raw)["value"]


@pytest.mark.parametrize(
    "encoding",
    [
        lambda text: text,
        lambda text: quote(text, safe=""),
        lambda text: quote(quote(text, safe=""), safe=""),
    ],
)
def test_B05_unexpected_credential_content_rejected_without_rendering(encoding):
    import json

    sentinel = "synthetic/private+marker"
    with pytest.raises(Rejection) as caught:
        sanitize_raw(json.dumps({"unexpected": encoding(sentinel)}).encode(), sentinel)
    assert str(caught.value) == "credential_in_source_content"
    assert sentinel not in str(caught.value)
