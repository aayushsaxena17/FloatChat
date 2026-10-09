"""Bounded raw sanitization preserving exact JSON numbers, never token fingerprints."""

import json
import re
from dataclasses import dataclass
from json.encoder import encode_basestring_ascii
from typing import Any
from urllib.parse import unquote

from .argovis import sanitize_source_url
from .json_stream import documents
from .numeric import MIB, PLAIN_NUMBER, Rejection, decode_json, exact_number

SECRET_FIELD = re.compile(
    r"(?:authorization|api[_-]?key|argo[_-]?key|password|secret|credential|token)", re.I
)


class RawNumber(str):
    """A JSON number kept as its written token; build it only through `raw_number`."""

    __slots__ = ()

    @property
    def source_token(self) -> str:
        return str(self)


def raw_number(token: str) -> RawNumber:
    # Same grammar, token, exponent and normalization limits as exact_number. A plain
    # token within the length cap cannot be rejected, so no Decimal is built for it.
    if PLAIN_NUMBER.fullmatch(token) is None or len(token) > 128:
        exact_number(token)
    return RawNumber(token)


_NUMBER_ONLY = frozenset({RawNumber})


@dataclass(frozen=True)
class SanitizedRaw:
    payload: bytes
    manifest: dict[str, int | str]


def sanitize_raw(raw: bytes, credential: str | None = None) -> SanitizedRaw:
    is_array = raw.lstrip().startswith(b"[")
    document = None if is_array else decode_json(raw, number_decoder=raw_number)
    counters = {"credential_fields_removed": 0, "urls_scrubbed": 0}

    def contains_secret(text: str) -> bool:
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

    def clean(value: Any) -> Any:
        # A number token is a str subclass: it must never reach the string checks.
        if type(value) is RawNumber:
            return value
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if SECRET_FIELD.search(key) or contains_secret(key):
                    counters["credential_fields_removed"] += 1
                    continue
                result[key] = item if type(item) is RawNumber else clean(item)
            return result
        if isinstance(value, list):
            if _NUMBER_ONLY.issuperset(map(type, value)):
                return value
            return [clean(item) for item in value]
        if isinstance(value, str):
            if "://" in value:
                scrubbed = sanitize_source_url(value)
                if scrubbed != value:
                    counters["urls_scrubbed"] += 1
                value = scrubbed
            if contains_secret(value):
                # Fail closed rather than silently changing identity/science.
                raise Rejection("credential_in_source_content")
        return value

    output = bytearray()

    def write(piece: str) -> None:
        encoded = piece.encode()
        if len(output) + len(encoded) > 128 * MIB:
            raise Rejection("sanitized_raw_size_limit")
        output.extend(encoded)

    def encode(value: Any) -> None:
        if type(value) is RawNumber:
            write(value)
        elif isinstance(value, dict):
            write("{")
            for index, (key, item) in enumerate(sorted(value.items())):
                write(("," if index else "") + encode_basestring_ascii(key) + ":")
                encode(item)
            write("}")
        elif isinstance(value, list):
            if _NUMBER_ONLY.issuperset(map(type, value)):
                write("[" + ",".join(value) + "]")  # At most 10,000 tokens of 128 bytes.
                return
            write("[")
            for index, item in enumerate(value):
                if index:
                    write(",")
                encode(item)
            write("]")
        elif isinstance(value, str):
            write(encode_basestring_ascii(value))
        else:
            write(json.dumps(value, ensure_ascii=True, allow_nan=False))

    if is_array:
        write("[")
        for index, item in enumerate(documents(raw, number_decoder=raw_number)):
            if index:
                write(",")
            encode(clean(item))
        write("]")
    else:
        encode(clean(document))
    return SanitizedRaw(bytes(output), {"version": "raw-sanitization-v1", **counters})
