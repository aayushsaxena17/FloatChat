"""N01-N08 policy unit coverage; persisted-pipeline acceptance is tracked separately."""

import hashlib
import json
import random
import re
import struct
import tracemalloc
from decimal import Decimal, localcontext
from functools import partial
from unittest.mock import patch

import pytest
from floatchat_core.ingestion import numeric
from floatchat_core.ingestion.numeric import (
    CanonicalBudget,
    Rejection,
    decimal_text,
    decode_json,
    exact_number,
    scientific_number,
)


@pytest.mark.parametrize("token", ["1", "1.0", "1e0", "1.000000", "10e-1"])
def test_N05_equivalent_numeric_tokens(token):
    assert decimal_text(exact_number(token)) == "1"
    number = scientific_number(exact_number(token))
    expected = b'{"exact":"1","flags":[],"missing_reason":null,"nonfinite_kind":null}'
    encoded, digest = CanonicalBudget().encode(number.canonical())
    assert encoded == expected
    assert digest == hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize("token", ["-0", "0e400", "-0.000", "0"])
def test_N04_signed_zero(token):
    number = scientific_number(exact_number(token))
    assert struct.pack(">d", number.value).hex() == "0000000000000000"
    assert number.exact == "0" and not number.flags


@pytest.mark.parametrize(
    "token,category",
    [
        ("1e100000000", "numeric_exponent_limit"),
        ("1e401", "numeric_exponent_limit"),
        ("1e-401", "numeric_exponent_limit"),
        ("0." + "1" * 127, "numeric_token_limit"),
        ("1e309", "float64_overflow"),
        ("1e400", "float64_overflow"),
        ("1e-400", "float64_underflow"),
        ("-1e-400", "float64_underflow"),
    ],
)
def test_N01_N04_rejections(token, category):
    with pytest.raises(Rejection, match=category):
        scientific_number(exact_number(token))


def test_N01_at_limit_before_decimal():
    token = "0." + "1" * 126
    assert len(token) == 128
    assert exact_number(token) == Decimal(token)
    with pytest.raises(Rejection, match="numeric_token_limit"):
        exact_number(token + "1")


def test_N02_normalized_output_preflight():
    at_limit = "1" * 113 + "e400"
    assert len(at_limit) <= 128
    with pytest.raises(Rejection, match="canonical_output_limit"):
        exact_number(at_limit)
    assert len(decimal_text(exact_number("1" * 112 + "e400"))) == 512
    assert exact_number("0e-000400") == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"NaN",
        b"Infinity",
        b"+Infinity",
        b"-Infinity",
        b"[01]",
        b"[+1]",
        b"[.1]",
        b"[1.]",
        b'{"a":1,"a":2}',
    ],
)
def test_N07_strict_json(raw):
    with pytest.raises(Rejection):
        decode_json(raw)


@pytest.mark.parametrize("token", ["inf", "nan", "+NaN", " NaN", "Infinity ", "1", "1e0"])
def test_N07_quoted_nonstandard(token):
    with pytest.raises(Rejection, match="invalid_scientific_numeric_string"):
        scientific_number(token)


@pytest.mark.parametrize(
    "token,kind",
    [
        ("NaN", "nan"),
        ("Infinity", "positive_infinity"),
        ("+Infinity", "positive_infinity"),
        ("-Infinity", "negative_infinity"),
    ],
)
def test_N06_nonfinite_only_in_measurements(token, kind):
    number = scientific_number(token)
    assert number.value is None and number.missing_reason == "nonfinite"
    assert number.nonfinite_kind == kind
    expected = (
        '{"exact":null,"flags":[],"missing_reason":"nonfinite","nonfinite_kind":"' + kind + '"}'
    ).encode()
    assert CanonicalBudget().encode(number.canonical()) == (
        expected,
        hashlib.sha256(expected).hexdigest(),
    )
    with pytest.raises(Rejection):
        scientific_number(token, coordinate=True)


@pytest.mark.parametrize(
    "token,bits,flags",
    [
        ("5e-324", "0000000000000001", ("rounded", "subnormal")),
        ("0.1", "3fb999999999999a", ("rounded",)),
        (
            "1.00000000000000011102230246251565404236316680908203125",
            "3ff0000000000000",
            ("rounded",),
        ),
        (
            "1.00000000000000011102230246251565404236316680908203126",
            "3ff0000000000001",
            ("rounded",),
        ),
        (
            "1.00000000000000011102230246251565404236316680908203124",
            "3ff0000000000000",
            ("rounded",),
        ),
        ("1.7976931348623157e308", "7fefffffffffffff", ("rounded",)),
    ],
)
def test_N03_N05_independent_binary64_oracles(token, bits, flags):
    with localcontext() as context:
        context.prec = 2
        number = scientific_number(exact_number(token))
        assert struct.pack(">d", number.value).hex() == bits
        assert number.flags == flags
        assert number.exact == decimal_text(Decimal(token))


def test_N05_same_float_distinct_exact_hashes():
    a = scientific_number(exact_number("1.00000000000000001"))
    b = scientific_number(exact_number("1.00000000000000002"))
    assert a.value == b.value
    assert CanonicalBudget().encode(a.canonical())[1] != CanonicalBudget().encode(b.canonical())[1]


def test_S02_null_fill_uncertainty():
    assert scientific_number(None).missing_reason == "null"
    assert scientific_number(exact_number("99999")).missing_reason == "argo_fill"
    assert (
        scientific_number(exact_number("-999"), fills=(Decimal(-999),)).missing_reason
        == "declared_fill"
    )
    with pytest.raises(Rejection, match="negative_uncertainty"):
        scientific_number(exact_number("-0.1"), error=True)


def test_B01_structural_bounds():
    with pytest.raises(Rejection, match="json_depth_limit"):
        decode_json(b"[" * 33 + b"0" + b"]" * 33)
    assert decode_json(b"[" * 32 + b"0" + b"]" * 32)
    with pytest.raises(Rejection, match="json_string_limit"):
        decode_json(b'"' + b"a" * 65539 + b'"')
    with pytest.raises(Rejection, match="decompressed_size_limit"):
        decode_json(b"[1]", max_bytes=2)


@pytest.mark.parametrize("field", ["profile_limit", "chunk_limit", "run_limit"])
def test_N08_canonical_bounds_and_recovery_counter(field):
    data = {"a": "b"}
    budget = CanonicalBudget(**{field: 9})
    assert budget.encode(data)[0] == b'{"a":"b"}'
    restored = CanonicalBudget(run_used=budget.run_used, chunk_used=budget.chunk_used, **{field: 9})
    if field == "profile_limit":
        with pytest.raises(Rejection, match="canonical_output_limit"):
            restored.encode({"a": "bb"})
    else:
        with pytest.raises(Rejection, match="canonical_output_limit"):
            restored.encode(data)


# --- stage1-v4 package A: fast exact decode and C-encoded levels -----------------------
# The helpers below are the pre-v4 implementations, copied verbatim (limits made
# parameters where noted). They are oracles: the fast code must agree with them on every
# input, including the category and the order in which categories are raised.


def legacy_decimal_text(value):
    if not value.is_finite():
        raise Rejection("invalid_json_number")
    sign, digit_tuple, exponent_value = value.as_tuple()
    if not isinstance(exponent_value, int):
        raise Rejection("invalid_json_number")
    digits = "".join(str(d) for d in digit_tuple).lstrip("0")
    if not digits:
        return "0"
    exponent = exponent_value
    while digits.endswith("0"):
        digits = digits[:-1]
        exponent += 1
    point = len(digits) + exponent
    length = sign + (
        point if exponent >= 0 else len(digits) + 1 if point > 0 else 2 - point + len(digits)
    )
    if length > 512:
        raise Rejection(
            "canonical_output_limit",
            resource={
                "scope": "number",
                "operation": "normalization",
                "limit_bytes": 512,
                "used_bytes": 0,
                "requested_bytes": length,
            },
        )
    if exponent >= 0:
        text = digits + "0" * exponent
    elif point > 0:
        text = digits[:point] + "." + digits[point:]
    else:
        text = "0." + "0" * (-point) + digits
    return ("-" if sign else "") + text


def legacy_exact_number(token):
    if not numeric.NUMERIC.fullmatch(token):
        raise Rejection("invalid_json_number")
    if len(token) > 128:
        raise Rejection("numeric_token_limit")
    exponent = re.split("[eE]", token)
    if len(exponent) == 2:
        digits = exponent[1].lstrip("+-").lstrip("0") or "0"
        if len(digits) > 3 or int(digits) > 400:
            raise Rejection("numeric_exponent_limit")
    value = Decimal(token)
    legacy_decimal_text(value)
    return value


def legacy_prepass(raw, *, depth_limit=32, array_limit=10000, string_limit=6 * 64 * 1024 + 1):
    depth = 0
    quoted = escaped = False
    string_size = 0
    arrays = []  # opening delimiter, count, current element seen
    for byte in raw:
        if quoted:
            string_size += 1
            if string_size > string_limit:
                raise Rejection("json_string_limit")
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        else:
            if arrays and arrays[-1][0] == 91:
                if byte == 44:
                    arrays[-1][2] = 0
                elif byte not in b" \n\r\t]" and not arrays[-1][2]:
                    arrays[-1][1] += 1
                    arrays[-1][2] = 1
                    if arrays[-1][1] > array_limit:
                        raise Rejection("invalid_array_length")
            if byte == 34:
                quoted = True
                string_size = 0
            elif byte in (91, 123):
                depth += 1
                arrays.append([byte, 0, 0])
                if depth > depth_limit:
                    raise Rejection("json_depth_limit")
            elif byte in (93, 125):
                depth -= 1
                if arrays:
                    arrays.pop()


def legacy_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejection("duplicate_json_key")
        result[key] = value
    return result


def legacy_decode_json(raw, *, number_decoder=legacy_exact_number, prepass=legacy_prepass):
    prepass(raw)
    try:
        result = json.loads(
            raw,
            parse_int=number_decoder,
            parse_float=number_decoder,
            parse_constant=numeric._nonstandard,
            object_pairs_hook=legacy_object,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, Rejection):
            raise
        raise Rejection("invalid_json") from None
    pending = [result]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                size = len(item.encode("utf-8"))
            except UnicodeError:
                raise Rejection("invalid_json_unicode") from None
            if size > 64 * 1024:
                raise Rejection("json_string_limit")
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
    return result


def outcome(function, *args, **kwargs):
    """Result, or the category and resource evidence of a Rejection."""
    try:
        return ("ok", function(*args, **kwargs))
    except Rejection as error:
        return ("rejected", error.category, error.resource_evidence)


def random_digits(rng, length):
    return "".join(rng.choice("0000111223456789") for _ in range(length))


def random_token(rng):
    token = rng.choice(["", "", "-"]) + rng.choice(
        ["0", "1", random_digits(rng, rng.randint(1, 4))]
    )
    if rng.random() < 0.6:
        token += "." + random_digits(rng, rng.randint(1, 8))
    if rng.random() < 0.5:
        token += (
            rng.choice("eE") + rng.choice(["", "+", "-"]) + random_digits(rng, rng.randint(1, 4))
        )
    return token


def test_N01_N02_exact_number_agrees_with_pre_v4_on_swept_tokens():
    tokens = ["0", "-0", "0e400", "0e-400", "1", "-1", "1e400", "1e-400", "1e401", "01", "1.", ".1"]
    for sign in ("", "-"):
        for digits in (1, 2, 112, 113, 126, 127):
            for exponent in ("", "e0", "e1", "e-1", "e400", "e-400", "E+399", "e401", "e0400"):
                tokens.append(sign + "1" * digits + exponent)
                tokens.append(sign + "1" + "0" * digits + exponent)
                tokens.append(sign + "0." + "0" * digits + "1" + exponent)
                tokens.append(sign + "1." + "0" * digits + exponent)
                tokens.append(sign + "100." + "5" * (digits // 2) + exponent)
    rng = random.Random(20261008)
    tokens += [random_token(rng) for _ in range(6000)]
    for token in tokens:
        expected = outcome(legacy_exact_number, token)
        actual = outcome(exact_number, token)
        assert actual == expected, token
        if expected[0] == "ok":
            assert actual[1].as_tuple() == expected[1].as_tuple()


def test_N02_preflight_length_is_decimal_text_length():
    rng = random.Random(7)
    values = [Decimal(random_token(rng)) for _ in range(4000)]
    for sign in (0, 1):
        for digits in (
            (0,),
            (0, 0, 0),
            (0, 0, 5),
            (5, 0, 0),
            (1, 2, 3),
            (9,) * 112,
            (0, 0, *[7] * 50),
        ):
            for exponent in (-600, -112, -50, -3, -1, 0, 1, 3, 400, 450):
                values.append(Decimal((sign, digits, exponent)))
    for value in values:
        expected = outcome(decimal_text, value)
        assert expected == outcome(legacy_decimal_text, value)
        length = numeric._normalized_length(value)
        if expected[0] == "ok":
            assert length == len(expected[1]), value.as_tuple()
        else:
            assert expected[2]["requested_bytes"] == length > 512


def test_N05_decimal_text_is_unchanged_for_every_decimal_shape():
    rng = random.Random(1234)
    values = [Decimal(random_token(rng)) for _ in range(8000)]
    for _ in range(12000):
        digits = tuple(rng.choice((0, 0, 0, 1, 5, 9)) for _ in range(rng.randint(1, 30)))
        if rng.random() < 0.5:
            digits = tuple(rng.randint(0, 9) for _ in range(rng.randint(1, 30)))
        exponent = rng.choice(
            (0, 0, -1, -2, -5, -6, -7, -8, 1, 2, 3, -20, -40, 25, rng.randint(-60, 60))
        )
        values.append(Decimal((rng.randint(0, 1), digits, exponent)))
    for text in (
        "0",
        "-0",
        "0.0",
        "-0.00",
        "0E+3",
        "-0E-9",
        "1000",
        "1.000",
        "100E-2",
        "1E+2",
        "0.000001",
        "0.0000001",
        "123456789012345678901234567890.1000",
        "1E-7",
        "5E-324",
        "1" + "0" * 511,
        "1" + "0" * 512,
        "0." + "0" * 505 + "1",
        "0." + "0" * 511 + "1",
        "1." + "0" * 600,
        "1" + "0" * 600 + ".5",
        "-" + "9" * 513,
        "NaN",
        "-Infinity",
        "sNaN",
    ):
        values.append(Decimal(text))
    for value in values:
        assert outcome(decimal_text, value) == outcome(legacy_decimal_text, value), repr(value)


def test_N02_signed_boundary_of_normalized_preflight():
    assert len(decimal_text(exact_number("1" * 112 + "e400"))) == 512
    with pytest.raises(Rejection) as caught:
        exact_number("-" + "1" * 112 + "e400")
    assert caught.value.category == "canonical_output_limit"
    assert caught.value.resource_evidence == {
        "scope": "number",
        "operation": "normalization",
        "limit_bytes": 512,
        "used_bytes": 0,
        "requested_bytes": 513,
    }
    # Trailing zeros of the coefficient are normalized away before the length is taken.
    assert numeric._normalized_length(Decimal("1" + "0" * 100 + "e400")) == 501


@pytest.mark.parametrize(
    "raw,category",
    [
        (b"[" * 33 + b"0" + b"]" * 33, "json_depth_limit"),
        (b'{"a":' * 33 + b"0" + b"}" * 33, "json_depth_limit"),
        (b"[{" * 17 + b"0" + b"}]" * 17, "json_depth_limit"),
        (b"[" * 33, "json_depth_limit"),  # Unbalanced: the cap is reached before the end.
        (b"[" + b"0," * 10000 + b"0]", "invalid_array_length"),
        (b'["a",' * 3 + b'{"b":[' + b"0," * 10000 + b"0]}]", "invalid_array_length"),
        (b"[" + b'"a",' * 10000 + b'"a"]', "invalid_array_length"),
        (b'"' + b"a" * 393217 + b'"', "json_string_limit"),
        (b'"' + b"\\n" * 196609 + b'"', "json_string_limit"),
        (b'"' + b"a" * 393250, "json_string_limit"),  # Unterminated and already over the cap.
        (b'{"a":1,"a":2,"k":"' + b"x" * 100000 + b'"}', "duplicate_json_key"),
        (b'{"a":1,"a":2,"k":"' + b"x" * 400000 + b'"}', "json_string_limit"),
        (b'["' + b"x" * 65537 + b'"]', "json_string_limit"),  # Decoded 64 KiB walk.
        (b"[0,,]", "invalid_json"),
        (b'["a]', "invalid_json"),
        (b'["a\\"]', "invalid_json"),
        (b'["\\ud800"]', "invalid_json_unicode"),
    ],
    ids=[
        "depth33_arrays",
        "depth33_objects",
        "depth33_mixed",
        "depth33_unbalanced",
        "array10001_numbers",
        "array10001_nested",
        "array10001_strings",
        "string_393217",
        "string_escapes_393218",
        "string_unterminated_over_cap",
        "duplicate_key_beats_100k_string",
        "string_cap_beats_duplicate_key",
        "string_65537_walk",
        "empty_element",
        "unterminated_string",
        "unterminated_escaped_quote",
        "lone_surrogate",
    ],
)
def test_B01_structural_caps_categories(raw, category):
    with pytest.raises(Rejection) as caught:
        decode_json(raw)
    assert caught.value.category == category
    assert repr(outcome(decode_json, raw)) == repr(outcome(legacy_decode_json, raw))


@pytest.mark.parametrize(
    "raw",
    [
        b"[" * 32 + b"0" + b"]" * 32,
        b'{"a":' * 31 + b"0" + b"}" * 31,
        b"[" + b"0," * 9999 + b"0]",
        b"[" + b'"a",' * 9999 + b'"a"]',
        b"[[" + b"0," * 6000 + b"0],[" + b"0," * 6000 + b"0]]",
        b'{"k":[' + b"0," * 9999 + b"0]," + b",".join(b'"k%d":0' % i for i in range(12000)) + b"}",
        b'["' + b"[" * 100 + b'"]',  # Brackets inside strings are not structure.
        b'["' + b"]}" * 100 + b'","]}"]',
        b'["' + b"," * 20000 + b'"]',
        b'["\\"]","\\\\","\\\\\\"]"]',
        b'{"a":"\\\\"}',
        b'"' + b"a" * 60000 + b'"',
        b"  [ 1 , 2 ]  ",
    ],
    ids=[
        "depth32_arrays",
        "depth31_objects",
        "array9999_numbers",
        "array9999_strings",
        "two_6000_arrays",
        "object_12000_keys",
        "brackets_in_string",
        "closers_in_string",
        "commas_in_string",
        "escaped_quote_and_backslash",
        "escaped_backslash_end",
        "string_60000",
        "whitespace",
    ],
)
def test_B01_structural_caps_accept_within_caps(raw):
    assert repr(outcome(decode_json, raw)) == repr(outcome(legacy_decode_json, raw))
    assert outcome(decode_json, raw)[0] == "ok"
    assert numeric._within_caps(raw) is True  # Cleared at C speed, no byte loop.


@pytest.mark.parametrize("escape", [False, True])
@pytest.mark.parametrize(
    "n,rejected", [(393214, False), (393216, False), (393217, True), (393218, True)]
)
def test_B01_string_cap_is_exact_at_the_prepass_bound(n, rejected, escape):
    body = b"a" * (n - 2) + b'\\"' if escape else b"a" * n
    raw = b'{"k":"' + body + b'"}'
    expected = outcome(legacy_prepass, raw)
    assert (expected[0] == "rejected") is rejected
    assert outcome(numeric._structural_caps, raw) == expected
    assert numeric._within_caps(raw) is not rejected


@pytest.mark.parametrize("count", [9998, 9999, 10000, 10001, 10002])
@pytest.mark.parametrize("shape", ["plain", "trailing", "empty_segments", "spaced", "nested"])
def test_B01_array_cap_is_exact_at_the_element_bound(count, shape):
    if shape == "plain":
        raw = b"[" + b",".join([b"0"] * count) + b"]"
    elif shape == "trailing":
        raw = b"[" + b",".join([b"0"] * count) + b",]"
    elif shape == "empty_segments":
        raw = b"[" + b"," * count + b"]"
    elif shape == "spaced":
        raw = b"[ " + b" , ".join([b"1"] * count) + b" ]"
    else:
        raw = b'{"a":[' + b",".join([b"[]"] * count) + b"]}"
    expected = outcome(legacy_prepass, raw)
    assert outcome(numeric._structural_caps, raw) == expected
    if count > 10000 and shape != "empty_segments":  # Commas alone are not elements.
        assert expected[:2] == ("rejected", "invalid_array_length")
    else:
        assert expected == ("ok", None)
    if expected[0] == "rejected":
        assert numeric._within_caps(raw) is False


def test_B01_filter_hands_hostile_shapes_to_the_byte_loop(monkeypatch):
    # Many side-by-side deep structures would need one full pass per level; a payload above
    # the scan size, or one that shrinks too slowly, is decided by the byte loop instead.
    deep = b"[" * 20 + b"1" + b"]" * 20
    slow = b"[" + b",".join([deep] * 300) + b"]"
    assert numeric._within_caps(slow) is False
    assert outcome(numeric._structural_caps, slow) == outcome(legacy_prepass, slow) == ("ok", None)
    shallow = b"[" + b",".join([b"[1]"] * 300) + b"]"
    assert numeric._within_caps(shallow) is True
    calls = []
    with monkeypatch.context() as patched:
        patched.setattr(numeric, "_SCAN_LIMIT", len(shallow) - 1)
        patched.setattr(numeric, "_within_caps", lambda raw: calls.append(raw) or True)
        assert outcome(numeric._structural_caps, shallow) == ("ok", None)
    assert calls == []  # Over the scan size: never reached the filter.
    bomb = b"[" * 40 + b"]" * 40
    assert outcome(numeric._structural_caps, bomb) == outcome(legacy_prepass, bomb)
    assert outcome(numeric._structural_caps, bomb)[1] == "json_depth_limit"


@pytest.mark.parametrize(
    "head,unit,tail",
    [
        (b"[", b'"",', b"0]"),
        (b"[", b"[],", b"0]"),
        (b"[", b"{},", b"0]"),
        (b"{", b'"a":[],', b'"z":0}'),
    ],
    ids=["quotes", "empty_arrays", "empty_objects", "object_members"],
)
def test_B01_token_dense_input_is_rejected_without_per_token_allocation(head, unit, tail):
    raw = head + unit * 140000 + tail
    assert len(raw) < numeric._SCAN_LIMIT
    assert numeric._within_caps(raw) is False
    expected = outcome(legacy_prepass, raw)  # Rejected for arrays; accepted inside an object.
    tracemalloc.start()
    try:
        actual = outcome(numeric._structural_caps, raw)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < 1 << 20  # A bytes object per token would be 10+ MB.


def test_B01_structural_scan_agrees_with_byte_loop_on_fuzzed_input(monkeypatch):
    # Small caps put every boundary within reach of short random inputs.
    limits = {"depth_limit": 3, "array_limit": 4, "string_limit": 7}
    monkeypatch.setattr(numeric, "_DEPTH_LIMIT", 3)
    monkeypatch.setattr(numeric, "_ARRAY_LIMIT", 4)
    monkeypatch.setattr(numeric, "_STRING_LIMIT", 7)
    rng = random.Random(4242)
    alphabet = ['"', "[", "]", "{", "}", ",", "\\", "0", "1", " ", "\n", "a", ":", '"', ",", "["]
    cleared = rejected = 0
    for _ in range(40000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40))).encode()
        expected = outcome(legacy_prepass, raw, **limits)
        assert outcome(numeric._structural_caps, raw) == expected, raw
        if numeric._within_caps(raw):
            assert expected == ("ok", None), raw  # Sound: cleared implies the loop accepts.
            cleared += 1
        elif expected[0] == "rejected":
            rejected += 1
    assert cleared > 1000 and rejected > 1000
    for _ in range(20000):  # Well-formed and damaged documents sit on the caps far more often.
        raw = damaged(rng, random_json(rng)).encode()
        expected = outcome(legacy_prepass, raw, **limits)
        assert outcome(numeric._structural_caps, raw) == expected, raw
        if numeric._within_caps(raw):
            assert expected == ("ok", None), raw


def random_json(rng, depth=0):
    kind = rng.random()
    if depth > 5 or kind < 0.3:
        return rng.choice(
            ["1", "-2.50", "3e2", "null", "true", '"s"', '"]}["', '"\\""', '"a,b"', '"\\\\"']
            + ['"\\u00e9\\n"']
        )
    if kind < 0.65:
        return "[" + ",".join(random_json(rng, depth + 1) for _ in range(rng.randint(0, 6))) + "]"
    keys = rng.sample(["a", "b", "c", "d", "e", "[", "}", ","], rng.randint(0, 4))
    return "{" + ",".join(f'"{k}":{random_json(rng, depth + 1)}' for k in keys) + "}"


def damaged(rng, text):
    for _ in range(rng.randint(0, 2)):  # Delete, duplicate or replace one character.
        if text:
            at = rng.randrange(len(text))
            text = text[:at] + rng.choice(["", text[at], '"', "]", ",", "["]) + text[at + 1 :]
    return text


def test_B01_decode_agrees_with_pre_v4_on_generated_and_damaged_documents(monkeypatch):
    monkeypatch.setattr(numeric, "_DEPTH_LIMIT", 4)
    monkeypatch.setattr(numeric, "_ARRAY_LIMIT", 5)
    prepass = partial(legacy_prepass, depth_limit=4, array_limit=5)
    rng = random.Random(99)
    categories = set()
    for _ in range(8000):
        raw = damaged(rng, random_json(rng)).encode()
        expected = outcome(legacy_decode_json, raw, prepass=prepass)
        assert repr(outcome(decode_json, raw)) == repr(expected), raw
        categories.add(expected[1] if expected[0] == "rejected" else "ok")
    assert categories >= {
        "ok",
        "invalid_json",
        "json_depth_limit",
        "invalid_array_length",
        "duplicate_json_key",
    }


def big_string(size, char="x"):
    return '"' + char * size + '"'


@pytest.mark.parametrize(
    "document",
    [
        '["\\ud800"]',
        '["\\udc00x"]',
        '["\\ud83d\\ude00"]',  # A valid pair is fine.
        "[" + big_string(70000) + ',"\\ud800"]',  # Walk order: the last element is checked first.
        '["\\ud800",' + big_string(70000) + "]",
        '{"a":' + big_string(70000) + ',"b":"\\ud800"}',
        '{"b":"\\ud800","a":' + big_string(70000) + "}",
        "{" + big_string(70000) + ":1}",
        '{"\\ud800":[1,2,3]}',
        "[1,2,[3,4,{" + '"k":[5,"\\ud800"]' + "}],6," + big_string(66000) + "]",
        "[1,2,[3,4,{" + '"k":[5,"ok"]' + "}],6," + big_string(65536) + "]",
        "[" + big_string(65537) + "]",
        "[" + big_string(65536) + "]",
        "[" + big_string(32768, "é") + "]",  # 65,536 decoded bytes.
        "[" + big_string(32769, "é") + "]",  # 65,538 decoded bytes.
        '["' + "\\u00e9" * 40000 + '"]',  # 240,000 source bytes, 80,000 decoded.
        '[1,"\\ud800",null,true,2.5,[7,' + big_string(66000) + ',8],{"a":9,"b":[10]}]',
    ],
    ids=[
        "surrogate_alone",
        "surrogate_low",
        "surrogate_pair_ok",
        "long_then_surrogate",
        "surrogate_then_long",
        "dict_long_then_surrogate",
        "dict_surrogate_then_long",
        "long_key",
        "surrogate_key",
        "nested_surrogate_then_long",
        "nested_ok_at_limit",
        "string_65537",
        "string_65536",
        "multibyte_65536",
        "multibyte_65538",
        "escapes_80000",
        "mixed_scalars",
    ],
)
def test_B01_string_walk_precedence_matches_pre_v4(document):
    raw = document.encode()
    assert repr(outcome(decode_json, raw)) == repr(outcome(legacy_decode_json, raw))


def reference_pieces(content, encoder, remaining):
    """Pre-v4 stream with every level streamed (its C fast path could never raise)."""
    if type(content) is not dict or type(content.get("levels")) is not list:
        yield from encoder.iterencode(content)
        return
    if any(type(key) is not str for key in content):
        yield from encoder.iterencode(content)
        return
    yield "{"
    for index, key in enumerate(sorted(content)):
        if index:
            yield ","
        yield from encoder.iterencode(key)
        yield ":"
        if key != "levels":
            yield from encoder.iterencode(content[key])
            continue
        yield "["
        for level_index, level in enumerate(content[key]):
            if level_index:
                yield ","
            yield from encoder.iterencode(level)
        yield "]"
    yield "}"


def encode_outcome(budget, content):
    try:
        result = ("ok", *budget.encode(content))
    except Rejection as error:
        result = ("rejected", error.category, error.resource_evidence)
    except (TypeError, ValueError, RecursionError) as error:
        result = ("error", type(error).__name__, str(error))
    return result, budget.run_used, budget.chunk_used


LEVEL_CONTENTS = [
    {"a": 1, "levels": [{"value": "123456789", "qc": "1"}]},
    {
        "z": None,
        "levels": [{"v": "1.5", "q": "1"}, {"v": "22", "q": "2", "n": {"b": [1, 2], "a": 0}}, {}],
        "a": "profile",
    },
    {"levels": [{"u": '\U0001f30aé\n\\"', "x": 1.25}, [1, 2, 3], "text", 7, None]},
    {"levels": [], "meta": {"k": ["v", {"s": 1}]}},
    {"levels": [{"value": float("nan")}]},
    {"levels": [{"ok": 1}, {"bad": object()}]},
    {"levels": [{"ok": "abc"}, {"value": float("inf"), "after": "x" * 20}]},
]


@pytest.mark.parametrize("index", range(len(LEVEL_CONTENTS)))
@pytest.mark.parametrize("scope", ["profile", "chunk", "run"])
def test_N08_c_encoded_levels_charge_exactly_like_the_streaming_encoder(index, scope):
    content = LEVEL_CONTENTS[index]
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        total = len("".join(reference_pieces(content, encoder, lambda: 0)))
    except (TypeError, ValueError):
        total = 200  # Content that cannot be encoded: sweep a fixed range of limits.
    outcomes = set()
    for limit in range(1, total + 3):
        fast = CanonicalBudget(**{scope + "_limit": limit})
        reference = CanonicalBudget(**{scope + "_limit": limit})
        with patch.object(numeric, "_canonical_pieces", reference_pieces):
            expected = encode_outcome(reference, content)
        assert encode_outcome(fast, content) == expected, limit
        outcomes.add(expected[0][0])
    assert "rejected" in outcomes or "error" in outcomes


def test_N08_rejects_at_a_level_boundary_with_the_streaming_charges():
    levels = [{"v": "1.5", "q": "1"}, {"v": "22", "q": "2"}, {"v": "333", "q": "3"}]
    content = {"levels": levels}
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    ends, offset = [], len('{"levels":[')
    for index, level in enumerate(levels):
        offset += len(encoder.encode(level)) + (1 if index else 0)
        ends.append(offset)
    for end in ends:
        for limit in (end - 1, end):
            budget = CanonicalBudget(profile_limit=limit)
            with pytest.raises(Rejection) as caught:
                budget.encode(content)
            # A level's own last piece (or the piece after it) crosses the limit by one byte,
            # not the whole encoded level as a single request.
            assert caught.value.resource_evidence == {
                "scope": "profile",
                "operation": "encoding",
                "limit_bytes": limit,
                "used_bytes": limit,
                "requested_bytes": 1,
            }
            assert budget.run_used == budget.chunk_used == limit + 1
    whole = encoder.encode(content).encode()
    assert CanonicalBudget(profile_limit=len(whole)).encode(content)[0] == whole


def test_N08_fitting_levels_are_c_encoded_and_only_oversized_levels_are_streamed():
    levels = [{"v": str(i), "q": "1"} for i in range(5)]
    streamed = []
    original = json.JSONEncoder.iterencode

    def spy(self, o, _one_shot=False):
        if not _one_shot:  # encode() reaches iterencode one-shot; only streaming counts.
            streamed.append(o)
        return original(self, o, _one_shot)

    with patch.object(json.JSONEncoder, "iterencode", spy):
        CanonicalBudget().encode({"levels": levels, "a": "b"})
        assert not any(isinstance(item, dict) for item in streamed)
        streamed.clear()
        with pytest.raises(Rejection):
            CanonicalBudget(profile_limit=30).encode({"levels": levels, "a": "b"})
        assert levels[0] in streamed
