import json
import random
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from floatchat_core.ingestion import raw as raw_module
from floatchat_core.ingestion.argovis import sanitize_source_url
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import MIB, Rejection, decode_json, exact_number
from floatchat_core.ingestion.raw import RawNumber, raw_number, sanitize_raw


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


# --- stage1-v4 package A: token-capturing sanitization ------------------------------------
# `legacy_sanitize_raw` is the pre-v4 implementation (RawNumber was a Decimal subclass and
# every piece was written through json.dumps), copied verbatim with the output cap as a
# parameter. The fast path must produce the same bytes, counters and rejections.

SECRET_FIELD = re.compile(
    r"(?:authorization|api[_-]?key|argo[_-]?key|password|secret|credential|token)", re.I
)


class LegacyRawNumber(Decimal):
    source_token: str

    def __new__(cls, token):
        exact_number(token)
        instance = super().__new__(cls, token)
        instance.source_token = token
        return instance


def legacy_sanitize_raw(raw, credential=None, *, limit=128 * MIB):
    is_array = raw.lstrip().startswith(b"[")
    document = None if is_array else decode_json(raw, number_decoder=LegacyRawNumber)
    counters = {"credential_fields_removed": 0, "urls_scrubbed": 0}

    def contains_secret(text):
        if not credential:
            return False
        for _ in range(4):
            if credential in text:
                return True
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
        return False

    def clean(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if SECRET_FIELD.search(key) or contains_secret(key):
                    counters["credential_fields_removed"] += 1
                    continue
                result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            if "://" in value:
                scrubbed = sanitize_source_url(value)
                if scrubbed != value:
                    counters["urls_scrubbed"] += 1
                value = scrubbed
            if contains_secret(value):
                raise Rejection("credential_in_source_content")
        return value

    output = bytearray()

    def write(piece):
        encoded = piece.encode()
        if len(output) + len(encoded) > limit:
            raise Rejection("sanitized_raw_size_limit")
        output.extend(encoded)

    def encode(value):
        if isinstance(value, LegacyRawNumber):
            write(value.source_token)
        elif isinstance(value, dict):
            write("{")
            for index, (key, item) in enumerate(sorted(value.items())):
                if index:
                    write(",")
                write(json.dumps(key, ensure_ascii=True))
                write(":")
                encode(item)
            write("}")
        elif isinstance(value, list):
            write("[")
            for index, item in enumerate(value):
                if index:
                    write(",")
                encode(item)
            write("]")
        else:
            write(json.dumps(value, ensure_ascii=True, allow_nan=False))

    if is_array:
        write("[")
        for index, item in enumerate(documents(raw, number_decoder=LegacyRawNumber)):
            if index:
                write(",")
            encode(clean(item))
        write("]")
    else:
        encode(clean(document))
    return bytes(output), {"version": "raw-sanitization-v1", **counters}


def sanitized(function, raw, credential, **kwargs):
    try:
        result = function(raw, credential, **kwargs)
    except Rejection as error:
        return "rejected", error.category, error.resource_evidence
    if isinstance(result, tuple):
        return "ok", result[0], result[1]
    return "ok", result.payload, result.manifest


SYNTHETIC_CREDENTIAL = "synthetic-credential-sentinel"
ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILES = sorted(
    path
    for path in (ROOT / "tests/fixtures/argovis").rglob("*.json")
    if path.name != "manifest.json"
)


def test_B04_number_tokens_are_str_subclass_tokens_validated_like_exact_number():
    token = raw_number("1.00e0")
    assert type(token) is RawNumber and token == "1.00e0" and token.source_token == "1.00e0"
    assert not isinstance(token, Decimal)
    for bad, category in (
        ("1e401", "numeric_exponent_limit"),
        ("0." + "1" * 127, "numeric_token_limit"),
        ("01", "invalid_json_number"),
        ("1" * 113 + "e400", "canonical_output_limit"),
    ):
        with pytest.raises(Rejection, match=category):
            raw_number(bad)
        with pytest.raises(Rejection, match=category):
            exact_number(bad)


def test_B04_raw_number_rejects_exactly_what_exact_number_rejects():
    rng = random.Random(5)
    tokens = ["0", "-0", "1e400", "1e401", "01", "1.", "-", "", "1e", "1E+0400", "0e999"]
    for sign in ("", "-"):
        for digits in (1, 100, 112, 113, 126, 127, 128, 129):
            tokens += [
                sign + "1" * digits,
                sign + "1" * digits + "e400",
                sign + "0." + "1" * digits,
            ]
    for _ in range(4000):
        token = rng.choice(["", "-"]) + rng.choice(["0", "7", str(rng.randint(1, 99999))])
        if rng.random() < 0.6:
            token += "." + "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 9)))
        if rng.random() < 0.4:
            token += rng.choice("eE") + rng.choice(["", "+", "-"]) + str(rng.randint(0, 1200))
        tokens.append(token)
    for token in tokens:
        try:
            expected = ("ok", exact_number(token) is not None)
        except Rejection as error:
            expected = ("rejected", error.category, error.resource_evidence)
        try:
            actual = ("ok", raw_number(token) == token)
        except Rejection as error:
            actual = ("rejected", error.category, error.resource_evidence)
        assert actual == expected, token


def test_B04_recorded_fixtures_sanitize_byte_identically_to_pre_v4():
    assert len(FIXTURE_FILES) >= 10
    for path in FIXTURE_FILES:
        data = path.read_bytes()
        for credential in (None, SYNTHETIC_CREDENTIAL):
            actual = sanitized(sanitize_raw, data, credential)
            assert actual == sanitized(legacy_sanitize_raw, data, credential), path
            if path.parent.parent.name == "recorded" and actual[0] == "ok":
                assert actual[1] == data  # Recorded payloads were stored already sanitized.


CRAFTED = [
    b'{"v":[1,2,3],"w":1.5,"x":"ok"}',
    b'{"a":[1.00,-0,1E+2,0e400,1e-400,12345678901234567890.123456789e-5],"b":[]}',
    b'[{"a":[1,"x",null,true,[2,3],{"k":4}],"b":{"z":[],"y":[1],"x":{}}},{"c":-1e0}]',
    b'[{"\\u00e9":"\\u00e9\\ud83d\\ude00\\n\\"\\\\/","a":1},{"k\\u0000":0.0}]',
    b'{"b":2,"a":1,"B":3,"\\u00fc":4,"\\ud83d\\ude00":5}',
    b'{"u":"https://user:synthetic-credential-sentinel@official.test/a?key=synthetic-'
    b'credential-sentinel#f","n":[1,2],"api_key":"x","nested":{"Authorization":1,"ok":[1,2]}}',
    b'[{"url":"https://a.test/x?token=1&b=2","n":1.5},{"url":"http://b.test/y","n":[1]}]',
    b'{"x":"a1b"}',
    b'{"x":["fine",{"y":"synthetic-credential-sentinel"}]}',
    b'{"synthetic-credential-sentinel":1}',
    b"  \n [ ] ",
    b"{}",
    b"[]",
    b"[{}]",
    b'{"e":1e999999999}',
    b'{"e":[1,2,1e401]}',
    b'[{"e":' + b"1" * 129 + b"}]",
    b'{"e":[' + b"1," * 9999 + b"1]}",
    b'{"e":[' + b"1," * 10000 + b"1]}",
    b'{"n":[NaN]}',
    b'{"s":"\\ud800"}',
    b'{"s":"' + b"x" * 70000 + b'"}',
    b'[{"a":1},{"a":2},',
    b'{"a":1}{"b":2}',
    b'{"a":1,"a":2}',
    b'{"e":01}',
    b"not json",
    b'{"e":[' + b"1.5e-3," * 500 + b"0]}",
]


@pytest.mark.parametrize("credential", [None, SYNTHETIC_CREDENTIAL, "1", "a", "5", "e"])
@pytest.mark.parametrize("index", range(len(CRAFTED)))
def test_B04_crafted_documents_sanitize_identically_to_pre_v4(index, credential):
    raw = CRAFTED[index]
    expected = sanitized(legacy_sanitize_raw, raw, credential)
    assert sanitized(sanitize_raw, raw, credential) == expected


def test_B04_crafted_documents_exercise_success_and_each_rejection():
    outcomes = [sanitized(legacy_sanitize_raw, raw, SYNTHETIC_CREDENTIAL) for raw in CRAFTED]
    assert sum(item[0] == "ok" for item in outcomes) >= 12
    assert {item[1] for item in outcomes if item[0] == "rejected"} >= {
        "credential_in_source_content",
        "numeric_exponent_limit",
        "numeric_token_limit",
        "invalid_array_length",
        "invalid_json_number",
        "invalid_json_unicode",
        "json_string_limit",
        "duplicate_json_key",
        "invalid_json",
    }


def test_B04_number_tokens_never_reach_the_credential_scan():
    # A numeric credential must not match the digits of a number token.
    result = sanitize_raw(b'{"v":[1,2,3],"w":1.5}', "1")
    assert result.payload == b'{"v":[1,2,3],"w":1.5}'
    with pytest.raises(Rejection, match="credential_in_source_content"):
        sanitize_raw(b'{"v":[1],"w":"a1"}', "1")


def test_B04_output_cap_rejects_with_the_same_category(monkeypatch):
    monkeypatch.setattr(raw_module, "MIB", 8)  # 128 * MIB == 1024 output bytes.
    for count in (100, 150, 200, 400):
        raw = b'{"e":[' + b"1.5," * count + b"0]}"
        assert sanitized(sanitize_raw, raw, None) == sanitized(
            legacy_sanitize_raw, raw, None, limit=1024
        )
        raw = b"[" + b",".join([b'{"e":1.5,"f":"xxxxxxxx"}'] * count) + b"]"
        assert sanitized(sanitize_raw, raw, None) == sanitized(
            legacy_sanitize_raw, raw, None, limit=1024
        )
    outcome = sanitized(sanitize_raw, b'{"e":[' + b"1.5," * 400 + b"0]}", None)
    assert outcome[:2] == ("rejected", "sanitized_raw_size_limit")


def random_value(rng, depth=0):
    kind = rng.random()
    if depth > 3 or kind < 0.45:
        return rng.choice(
            [
                "1",
                "-2.50",
                "3E+2",
                "0.1000000000000000001",
                "null",
                "false",
                '"s"',
                '"https://u:p@h.test/x?key=1#f"',
                '"caf\\u00e9\\n"',
                '"a/b\\\\c"',
                '"1"',
            ]
        )
    if kind < 0.7:
        return "[" + ",".join(random_value(rng, depth + 1) for _ in range(rng.randint(0, 5))) + "]"
    keys = rng.sample(
        ["b", "a", "Z", "\\u00e9", "api_key", "k1", "k2", "token_x"], rng.randint(0, 5)
    )
    return "{" + ",".join(f'"{k}":{random_value(rng, depth + 1)}' for k in keys) + "}"


def test_B04_generated_documents_sanitize_identically_to_pre_v4():
    rng = random.Random(8)
    seen = set()
    for _ in range(3000):
        values = [random_value(rng) for _ in range(rng.randint(1, 3))]
        text = "[" + ",".join('{"d":' + value + "}" for value in values) + "]"
        if rng.random() < 0.4:
            text = values[0] if values[0].startswith("{") else '{"d":' + values[0] + "}"
        raw = text.encode()
        credential = rng.choice([None, None, "1", "u:p", "s"])
        expected = sanitized(legacy_sanitize_raw, raw, credential)
        assert sanitized(sanitize_raw, raw, credential) == expected, raw
        seen.add(expected[0] + (expected[1] if expected[0] == "rejected" else ""))
    assert "ok" in seen and "rejectedcredential_in_source_content" in seen
