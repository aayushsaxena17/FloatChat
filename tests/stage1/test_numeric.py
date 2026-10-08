"""N01-N08 policy unit coverage; persisted-pipeline acceptance is tracked separately."""

import hashlib
import struct
from decimal import Decimal, localcontext

import pytest
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
