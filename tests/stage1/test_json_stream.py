import random

import pytest
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import Rejection, decode_json, exact_number
from floatchat_core.ingestion.raw import RawNumber, raw_number


def test_stream_preserves_decimal_lexemes_and_braces_in_strings():
    rows = list(documents(b'[{"n":1.00e0,"s":"}\\"["},{"n":2}]', number_decoder=raw_number))
    assert type(rows[0]["n"]) is RawNumber
    assert rows[0]["n"] == "1.00e0" and rows[0]["n"].source_token == "1.00e0"
    assert rows[0]["s"] == '}"['
    assert rows[1]["n"] == "2"


@pytest.mark.parametrize(
    "raw",
    [b"[{}", b"[{},]", b"[{}]x", b"[{} {}]", b"[{}],[]", b"[", b"[1]", b"{}"],
)
def test_stream_rejects_incomplete_or_noncontract_response(raw):
    with pytest.raises(Rejection):
        list(documents(raw))


def test_stream_bound_checks_before_decoding_extra_profile():
    iterator = documents(b'[{"n":1},{"n":1e100000000}]', max_documents=1)
    assert next(iterator)["n"] == 1
    with pytest.raises(Rejection, match="profile_count_limit"):
        next(iterator)


def test_stream_empty_is_valid_json_but_proves_no_inventory_by_itself():
    assert list(documents(b" \n[]\t")) == []


def test_stream_outer_array_counts_toward_depth_bound():
    raw = b'[{"v":' + b"[" * 30 + b"0" + b"]" * 30 + b"}]"
    assert len(list(documents(raw))) == 1
    with pytest.raises(Rejection, match="json_depth_limit"):
        list(documents(raw.replace(b":", b":[").replace(b"}", b"]}")))


# --- stage1-v4 package A: regex-token document splitting ---------------------------------
# `legacy_documents` is the pre-v4 byte-at-a-time splitter, copied verbatim. The fast
# splitter must yield the same documents and raise the same category at the same point.


def legacy_documents(raw, *, max_documents=2000, number_decoder=exact_number):
    if not 0 < max_documents <= 2000 or len(raw) > 128 * 1024 * 1024:
        raise Rejection("decompressed_size_limit")
    length = len(raw)
    cursor = 0

    def whitespace(position):
        while position < length and raw[position] in b" \n\r\t":
            position += 1
        return position

    cursor = whitespace(cursor)
    if cursor >= length or raw[cursor] != 91:
        raise Rejection("unsupported_response_schema")
    cursor = whitespace(cursor + 1)
    count = 0
    if cursor < length and raw[cursor] == 93:
        if whitespace(cursor + 1) != length:
            raise Rejection("invalid_json")
        return
    while cursor < length:
        if raw[cursor] != 123:
            raise Rejection("unsupported_response_schema")
        first = cursor
        depth = 0
        quoted = escaped = False
        while cursor < length:
            char = raw[cursor]
            if quoted:
                if escaped:
                    escaped = False
                elif char == 92:
                    escaped = True
                elif char == 34:
                    quoted = False
            elif char == 34:
                quoted = True
            elif char in (123, 91):
                depth += 1
                if depth + 1 > 32:
                    raise Rejection("json_depth_limit")
            elif char in (125, 93):
                depth -= 1
                if depth == 0:
                    cursor += 1
                    break
            cursor += 1
        if depth or quoted:
            raise Rejection("invalid_json")
        count += 1
        if count > max_documents:
            raise Rejection("profile_count_limit")
        value = decode_json(raw[first:cursor], number_decoder=number_decoder)
        if not isinstance(value, dict):
            raise Rejection("unsupported_response_schema")
        yield value
        cursor = whitespace(cursor)
        if cursor >= length:
            break
        if raw[cursor] == 93:
            if whitespace(cursor + 1) != length:
                raise Rejection("invalid_json")
            return
        if raw[cursor] != 44:
            raise Rejection("invalid_json")
        cursor = whitespace(cursor + 1)
    raise Rejection("invalid_json")


def drain(iterator):
    """Every document yielded before the stream ended, and how it ended."""
    rows = []
    try:
        for row in iterator:
            rows.append(row)
    except Rejection as error:
        return rows, error.category, error.resource_evidence
    return rows, None, None


def nested(levels):
    return b'{"v":' + b"[" * levels + b"0" + b"]" * levels + b"}"


@pytest.mark.parametrize(
    "raw",
    [
        b'[{"a":"}"},{"b":"]"}]',
        b'[{"a":"\\"}"},{"b":"\\\\"},{"c":"\\\\\\""}]',
        b'[{"a":"[{"},\n\t{"b":[{"c":[]}]} ,\r\n{}]',
        b' \n[ {"a":1} , {"a":2} ] \t',
        b"[]",
        b"[ ]x",
        b"[{}",
        b"[{},",
        b"[{},]",
        b'[{"a":"x}',
        b'[{"a":"x\\',
        b'[{"a":"x"',
        b'[{"a":"x\\"}]',
        b'[{"a":1]]',
        b"[{]",
        b"[{}}",
        b'[{"a":[}]',
        b'[{"a":1}] x',
        b'[{"a":1},{"a":1e999999999}]',
        b'[{"a":1},[]]',
        b'[{"a":1}{"a":2}]',
        b'[{"a":1}\\{"a":2}]',
        b"[{}]\\",
        b'["a"]',
        b"{}",
        b"",
        b"   ",
        b'[{"a":1},{"a":1},{"a":1}]',
        b'[{"a":"\xff"}]',
        b'[{"a":NaN}]',
        b'[{"a":"' + b"x" * 70000 + b'"}]',
        b'[{"k":' + b"[0," * 20 + b"0]" + b",0]" * 20 + b"}]",
    ]
    + [b"[" + nested(k) + b"]" for k in range(28, 35)]
    + [b"[" + nested(31) + b"," + nested(32) + b"]", b"[" + nested(32) + b"," + nested(99) + b"]"],
)
@pytest.mark.parametrize("limit", [1, 2, 2000])
def test_stream_agrees_with_pre_v4_splitter(raw, limit):
    assert repr(drain(documents(raw, max_documents=limit))) == repr(
        drain(legacy_documents(raw, max_documents=limit))
    )


def random_document(rng, depth=0):
    kind = rng.random()
    if depth > 4 or kind < 0.35:
        return rng.choice(["1", "2.50", "null", '"s"', '"}{]["', '"\\""', '"\\\\"', "[]", "{}"])
    if kind < 0.65:
        return (
            "[" + ",".join(random_document(rng, depth + 1) for _ in range(rng.randint(0, 3))) + "]"
        )
    keys = rng.sample(["a", "b", "c", "}", "]", '\\"'], rng.randint(0, 3))
    return "{" + ",".join(f'"{k}":{random_document(rng, depth + 1)}' for k in keys) + "}"


def test_stream_agrees_with_pre_v4_splitter_on_generated_and_damaged_responses():
    rng = random.Random(31)
    ends = set()
    for _ in range(12000):
        docs = [
            "{" + ",".join(f'"k{i}":{random_document(rng)}' for i in range(rng.randint(0, 2))) + "}"
            for _ in range(rng.randint(0, 3))
        ]
        text = rng.choice(["[", " [", "["]) + rng.choice([",", ", ", ",\n"]).join(docs) + "]"
        for _ in range(rng.randint(0, 3)):  # Delete, duplicate or replace one character.
            if text:
                at = rng.randrange(len(text))
                replacement = rng.choice(["", text[at], '"', "]", "}", ",", "[", "{", "\\"])
                text = text[:at] + replacement + text[at + 1 :]
        raw = text.encode()
        limit = rng.choice([1, 2, 2000])
        expected = drain(legacy_documents(raw, max_documents=limit))
        assert repr(drain(documents(raw, max_documents=limit))) == repr(expected), raw
        ends.add(expected[1])
    assert {None, "invalid_json", "unsupported_response_schema", "profile_count_limit"} <= ends


def test_stream_deep_document_after_the_count_limit_is_reported_by_depth_first():
    raw = b"[" + nested(1) + b"," + nested(40) + b"]"
    rows, category, _ = drain(documents(raw, max_documents=1))
    assert len(rows) == 1 and category == "json_depth_limit"
