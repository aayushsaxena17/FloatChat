"""Profile-at-a-time decoding of the pinned API's top-level object arrays."""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

from .numeric import Rejection, decode_json, exact_number


def documents(
    raw: bytes,
    *,
    max_documents: int = 2000,
    number_decoder: Callable[[str], Decimal] = exact_number,
) -> Iterator[dict[str, Any]]:
    if not 0 < max_documents <= 2000 or len(raw) > 128 * 1024 * 1024:
        raise Rejection("decompressed_size_limit")
    length = len(raw)
    cursor = 0

    def whitespace(position: int) -> int:
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
