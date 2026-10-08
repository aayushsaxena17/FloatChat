"""Bounded raw sanitization preserving exact JSON numbers, never token fingerprints."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

from .argovis import sanitize_source_url
from .json_stream import documents
from .numeric import MIB, Rejection, decode_json, exact_number

SECRET_FIELD = re.compile(
    r"(?:authorization|api[_-]?key|argo[_-]?key|password|secret|credential|token)", re.I
)


class RawNumber(Decimal):
    source_token: str

    def __new__(cls, token: str) -> "RawNumber":
        exact_number(token)
        instance = super().__new__(cls, token)
        instance.source_token = token
        return instance


@dataclass(frozen=True)
class SanitizedRaw:
    payload: bytes
    manifest: dict[str, int | str]


def sanitize_raw(raw: bytes, credential: str | None = None) -> SanitizedRaw:
    is_array = raw.lstrip().startswith(b"[")
    document = None if is_array else decode_json(raw, number_decoder=RawNumber)
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
        if isinstance(value, RawNumber):
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
        for index, item in enumerate(documents(raw, number_decoder=RawNumber)):
            if index:
                write(",")
            encode(clean(item))
        write("]")
    else:
        encode(clean(document))
    return SanitizedRaw(bytes(output), {"version": "raw-sanitization-v1", **counters})
