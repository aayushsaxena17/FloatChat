"""Bounded exact-source decoding and scientific-json-v2 canonicalization."""

import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

HASH_VERSION = "scientific-json-v2"
MIB = 1024 * 1024
NUMERIC = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def safe_resource_evidence(value: Any) -> dict[str, Any]:
    """Accept only fixed scopes/operations and bounded counters, never source text."""
    if not isinstance(value, dict) or set(value) != {
        "scope",
        "operation",
        "limit_bytes",
        "used_bytes",
        "requested_bytes",
    }:
        return {}
    if value["scope"] not in ("number", "profile", "chunk", "run") or value["operation"] not in (
        "normalization",
        "encoding",
        "reservation",
        "accounting",
        "readback",
    ):
        return {}
    if any(
        type(value[key]) is not int or not 0 <= value[key] < 2**63
        for key in ("limit_bytes", "used_bytes", "requested_bytes")
    ):
        return {}
    return dict(value)


class Rejection(ValueError):
    """Safe category only: never render untrusted source values or client errors."""

    def __init__(self, category: str, *, resource: dict[str, Any] | None = None) -> None:
        self.category = category
        self.resource_evidence = safe_resource_evidence(resource)
        super().__init__(category)


def exact_number(token: str) -> Decimal:
    if not NUMERIC.fullmatch(token):
        raise Rejection("invalid_json_number")
    if len(token) > 128:
        raise Rejection("numeric_token_limit")
    exponent = re.split("[eE]", token)
    if len(exponent) == 2:
        digits = exponent[1].lstrip("+-").lstrip("0") or "0"
        if len(digits) > 3 or int(digits) > 400:
            raise Rejection("numeric_exponent_limit")
    value = Decimal(token)
    decimal_text(value)  # Preflight before any exponent-free allocation.
    return value


def decimal_text(value: Decimal) -> str:
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


def _nonstandard(_: str) -> None:
    raise Rejection("invalid_json_number")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Rejection("duplicate_json_key")
        result[key] = value
    return result


def decode_json(
    raw: bytes,
    *,
    max_bytes: int = 128 * MIB,
    number_decoder: Callable[[str], Decimal] = exact_number,
) -> Any:
    if len(raw) > max_bytes:
        raise Rejection("decompressed_size_limit")
    # Prevent the recursive decoder allocating beyond the declared structural caps.
    depth = 0
    quoted = escaped = False
    string_size = 0
    # Array cardinality is checked before Decimal/list allocation. The pinned
    # wire schema has no legitimate array longer than one 10,000-level profile.
    arrays: list[list[int]] = []  # opening delimiter, count, current element seen
    for byte in raw:
        if quoted:
            string_size += 1
            # Worst-case JSON escape expansion is 6 source bytes per decoded byte.
            if string_size > 6 * 64 * 1024 + 1:
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
                    if arrays[-1][1] > 10000:
                        raise Rejection("invalid_array_length")
            if byte == 34:
                quoted = True
                string_size = 0
            elif byte in (91, 123):
                depth += 1
                arrays.append([byte, 0, 0])
                if depth > 32:
                    raise Rejection("json_depth_limit")
            elif byte in (93, 125):
                depth -= 1
                if arrays:
                    arrays.pop()
    try:
        result = json.loads(
            raw,
            parse_int=number_decoder,
            parse_float=number_decoder,
            parse_constant=_nonstandard,
            object_pairs_hook=_object,
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


@dataclass(frozen=True)
class ScientificNumber:
    value: float | None
    exact: str | None
    missing_reason: str | None = None
    nonfinite_kind: str | None = None
    flags: tuple[str, ...] = ()

    def canonical(self) -> dict[str, Any]:
        return {
            "exact": self.exact,
            "missing_reason": self.missing_reason,
            "nonfinite_kind": self.nonfinite_kind,
            "flags": list(self.flags),
        }


def scientific_number(
    token: Any, *, error: bool = False, fills: tuple[Decimal, ...] = (), coordinate: bool = False
) -> ScientificNumber:
    if token is None and not coordinate:
        return ScientificNumber(None, None, "null")
    if isinstance(token, str) and not coordinate:
        kinds = {
            "NaN": "nan",
            "Infinity": "positive_infinity",
            "+Infinity": "positive_infinity",
            "-Infinity": "negative_infinity",
        }
        if token not in kinds:
            raise Rejection("invalid_scientific_numeric_string")
        return ScientificNumber(None, None, "nonfinite", kinds[token])
    if not isinstance(token, Decimal):
        raise Rejection("invalid_scientific_number")
    text = decimal_text(token)
    if not coordinate:
        if token == Decimal(99999):
            return ScientificNumber(None, None, "argo_fill")
        if token in fills:
            return ScientificNumber(None, None, "declared_fill")
        if error and token < 0:
            raise Rejection("negative_uncertainty")
    rounded = float(token)  # CPython correctly rounded Decimal -> binary64, ties-even.
    if not math.isfinite(rounded):
        raise Rejection("float64_overflow")
    if token != 0 and rounded == 0:
        raise Rejection("float64_underflow")
    if token == 0:
        rounded = 0.0
    flags: list[str] = []
    if Decimal.from_float(rounded) != token:
        flags.append("rounded")
    if rounded != 0 and abs(rounded) < sys.float_info.min:
        flags.append("subnormal")
    return ScientificNumber(rounded, text, flags=tuple(flags))


@dataclass
class CanonicalBudget:
    """A run counter must be persisted by the controller before reprocessing."""

    run_used: int = 0
    chunk_used: int = 0
    profile_limit: int = 16 * MIB
    chunk_limit: int = 256 * MIB
    run_limit: int = 40 * 1024 * MIB  # stage1-v3 S1-RESOURCE-3 (ADR-0041)

    def __post_init__(self) -> None:
        if not (
            0 < self.profile_limit <= 16 * MIB
            and 0 < self.chunk_limit <= 256 * MIB
            and 0 < self.run_limit <= 40 * 1024 * MIB
        ):
            raise Rejection("invalid_canonical_budget")

    def encode(self, content: dict[str, Any]) -> tuple[bytes, str]:
        result = bytearray()
        digest = hashlib.sha256()
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)

        def remaining() -> int:
            return min(
                self.profile_limit - len(result),
                self.chunk_limit - self.chunk_used,
                self.run_limit - self.run_used,
            )

        for piece in _canonical_pieces(content, encoder, remaining):
            encoded = piece.encode("utf-8")
            self.run_used += len(encoded)
            self.chunk_used += len(encoded)
            # Existing precedence and charging remain unchanged; record the first
            # exceeded scope without including scientific content or JSON pieces.
            for scope, used, limit in (
                ("profile", len(result), self.profile_limit),
                ("chunk", self.chunk_used - len(encoded), self.chunk_limit),
                ("run", self.run_used - len(encoded), self.run_limit),
            ):
                if used + len(encoded) > limit:
                    raise Rejection(
                        "canonical_output_limit",
                        resource={
                            "scope": scope,
                            "operation": "encoding",
                            "limit_bytes": limit,
                            "used_bytes": used,
                            "requested_bytes": len(encoded),
                        },
                    )
            result.extend(encoded)
            digest.update(encoded)
        return bytes(result), digest.hexdigest()


def _small_json_bound(value: Any) -> int | None:
    """Bound a level before C encoding; unsupported/large structures stream normally.

    This walk produces no canonical bytes. Its conservative ASCII upper bound
    includes surrogate-pair escapes and applies only to exact JSON builtin types.
    """
    pending = [(value, 0)]
    size = nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 512 or depth > 16:
            return None
        if type(item) is str:
            size += 2 + 12 * len(item)
        elif item is None or type(item) is bool:
            size += 5
        elif type(item) is int and item.bit_length() <= 64:
            size += 21
        elif type(item) is float and math.isfinite(item):
            size += 32
        elif type(item) is dict and len(item) <= 512 and all(type(key) is str for key in item):
            size += 2 + 2 * len(item)
            pending.extend((key, depth + 1) for key in item)
            pending.extend((part, depth + 1) for part in item.values())
        elif type(item) is list:
            size += 2 + len(item)
            if len(item) > 512:
                return None
            pending.extend((part, depth + 1) for part in item)
        else:
            return None
        if size > 64 * 1024:
            return None
    return size


def _canonical_pieces(
    content: dict[str, Any], encoder: json.JSONEncoder, remaining: Callable[[], int]
) -> Iterator[str]:
    """C encode bounded levels while retaining the exact sorted JSON byte stream.

    A level uses the fast path only if its proven output bound fits every budget.
    Near a boundary the original streaming encoder preserves rejection precedence
    and actual-work charging, without allocating an unbounded encoded profile.
    """
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
            bound = _small_json_bound(level)
            if bound is not None and bound <= remaining():
                yield encoder.encode(level)
            else:
                yield from encoder.iterencode(level)
        yield "]"
    yield "}"
