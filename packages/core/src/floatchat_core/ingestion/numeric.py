"""Bounded exact-source decoding and scientific-json-v2 canonicalization."""

import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from itertools import compress, repeat
from typing import Any

HASH_VERSION = "scientific-json-v2"
MIB = 1024 * 1024
NUMERIC = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
# NUMERIC split by exponent: `PLAIN_NUMBER` is the common case, `_NUMBER` has the exponent
# (captured, so no second split is needed). Together they accept exactly NUMERIC's tokens.
PLAIN_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE]([+-]?[0-9]+)\Z")


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


def _layout_length(sign: int, count: int, exponent: int) -> int:
    """Length of the exponent-free text for `count` significant digits, no trailing zeros."""
    point = count + exponent
    return sign + (point if exponent >= 0 else count + 1 if point > 0 else 2 - point + count)


def _normalized_length(value: Decimal) -> int:
    """`len(decimal_text(value))` for a finite value, from its digit tuple alone.

    No digit string or normalized text is built, so the exact_number preflight costs
    a few integer operations; `decimal_text` shares `_layout_length`.
    """
    sign, digit_tuple, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    end = len(digit_tuple)
    start = 0
    while start < end and digit_tuple[start] == 0:
        start += 1
    if start == end:
        return 1
    zeros = 0
    while digit_tuple[end - 1 - zeros] == 0:
        zeros += 1
    return _layout_length(sign, end - start - zeros, exponent + zeros)


def _canonical_output_limit(length: int) -> Rejection:
    return Rejection(
        "canonical_output_limit",
        resource={
            "scope": "number",
            "operation": "normalization",
            "limit_bytes": 512,
            "used_bytes": 0,
            "requested_bytes": length,
        },
    )


def exact_number(token: str) -> Decimal:
    if PLAIN_NUMBER.fullmatch(token) is not None:
        if len(token) > 128:
            raise Rejection("numeric_token_limit")
        # Without an exponent the normalized text is no longer than the token (at most
        # 128 bytes), so the 512-byte preflight below cannot fail.
        return Decimal(token)
    match = _NUMBER.fullmatch(token)
    if match is None:
        raise Rejection("invalid_json_number")
    if len(token) > 128:
        raise Rejection("numeric_token_limit")
    digits = match.group(1).lstrip("+-").lstrip("0") or "0"
    if len(digits) > 3 or int(digits) > 400:
        raise Rejection("numeric_exponent_limit")
    value = Decimal(token)
    # Preflight before any exponent-free allocation; arithmetic only, no text built.
    length = _normalized_length(value)
    if length > 512:
        raise _canonical_output_limit(length)
    return value


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise Rejection("invalid_json_number")
    # str() is exact and positional, with no exponent, when the exponent is <= 0 and the
    # adjusted exponent >= -6; the normalized text is then that text without trailing
    # fraction zeros (and "-0" is "0"). Anything else, or a text long enough to need the
    # 512-byte check, takes the digit-tuple route below.
    text = str(value)
    if "E" not in text and len(text) <= 512:
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text == "-0" else text
    sign, digit_tuple, exponent_value = value.as_tuple()
    if not isinstance(exponent_value, int):
        raise Rejection("invalid_json_number")
    digits = "".join(map(str, digit_tuple)).lstrip("0")
    if not digits:
        return "0"
    exponent = exponent_value
    while digits.endswith("0"):
        digits = digits[:-1]
        exponent += 1
    point = len(digits) + exponent
    length = _layout_length(sign, len(digits), exponent)
    if length > 512:
        raise _canonical_output_limit(length)
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
    result = dict(pairs)
    if len(result) != len(pairs):
        raise Rejection("duplicate_json_key")
    return result


_DEPTH_LIMIT = 32
_ARRAY_LIMIT = 10000
# The C-speed filter holds a bytes object per string and per innermost pair (about 50
# bytes each), which the byte loop never did. Input with more than _TOKEN_LIMIT quotes and
# brackets, or larger than _SCAN_LIMIT, goes to the byte loop instead: a hostile payload is
# then rejected as cheaply as before (the filter's objects stay under ~15 MB) and real
# profile documents (a few hundred quotes and brackets, tens of KB to a few MB) stay on the
# fast path.
_TOKEN_LIMIT = 1 << 18
_SCAN_LIMIT = 8 * MIB
# Worst-case JSON escape expansion is 6 source bytes per decoded byte (+ closing quote).
_STRING_LIMIT = 6 * 64 * 1024 + 1
# One string token: opening quote to closing quote, or to the end of input when the
# string never closes (as the byte loop stays quoted to the end; each quote is consumed
# once, so the scan stays linear).
_STRINGS = re.compile(rb'("[^"\\]*(?:\\[\s\S][^"\\]*)*(?:"|\\?\Z))')
# A bracket pair with no bracket inside; each split peels one nesting level. Only the
# `[` pairs are captured: the byte loop counts the elements of arrays, not of objects.
_INNERMOST = re.compile(rb"(\[[^\[\]{}]*[\]}])|\{[^\[\]{}]*[\]}]")
_BRACKET = re.compile(rb"[\[\]{}]")
_CONTAINERS: frozenset[type] = frozenset({str, list, dict})


def _byte_caps(raw: bytes) -> None:
    """Reference structural scan: one Python iteration per byte, first violation raises."""
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
            if string_size > _STRING_LIMIT:
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
                    if arrays[-1][1] > _ARRAY_LIMIT:
                        raise Rejection("invalid_array_length")
            if byte == 34:
                quoted = True
                string_size = 0
            elif byte in (91, 123):
                depth += 1
                arrays.append([byte, 0, 0])
                if depth > _DEPTH_LIMIT:
                    raise Rejection("json_depth_limit")
            elif byte in (93, 125):
                depth -= 1
                if arrays:
                    arrays.pop()


def _within_caps(raw: bytes) -> bool:
    """True only if `_byte_caps` provably would not raise for `raw`.

    The filter is sound, never complete: it must not clear an input the byte loop
    rejects, and may decline one it accepts:
      * strings: the tokens are exactly the loop's quoted runs (the last one runs to the
        end of input if it never closes), and a run's `string_size` is `len(token) - 1`;
      * depth: with strings removed, the loop's depth is the bracket nesting depth, and
        one `_INNERMOST` split peels exactly one level, so a fully peeled input needs at
        most `_DEPTH_LIMIT` splits iff its depth is within the cap;
      * arrays: the loop counts at most one element per run between direct commas, so
        an array's count is at most its direct commas + 1; peeled children collapse to
        a single placeholder, so a pair's `,` count is its direct commas.
    """
    structural = sum(map(raw.count, (b'"', b"[", b"]", b"{", b"}")))  # No allocation.
    if structural > _TOKEN_LIMIT:
        return False
    parts = _STRINGS.split(raw)
    if len(parts) > 1 and max(map(len, parts[1::2])) - 1 > _STRING_LIMIT:
        return False
    skeleton = b"0".join(parts[0::2])  # strings collapse to one element placeholder
    budget = 4 * len(skeleton) + 4096  # Bytes the peeling passes may scan in total.
    for _ in range(_DEPTH_LIMIT):
        budget -= len(skeleton)
        if budget < 0:
            return False
        pieces = _INNERMOST.split(skeleton)
        if len(pieces) == 1:
            break
        arrays = filter(None, pieces[1::2])
        if max(map(bytes.count, arrays, repeat(b",")), default=0) >= _ARRAY_LIMIT:
            return False
        skeleton = b"0".join(pieces[0::2])
    return _BRACKET.search(skeleton) is None


def _structural_caps(raw: bytes) -> None:
    """Depth, array and string caps before the allocating decode, at C speed.

    `_within_caps` clears the input, or `_byte_caps` decides it: inputs over a cap,
    with an unterminated string or with unbalanced/mismatched brackets run the byte
    loop, which raises the original category in the original byte order. The scan is
    therefore at least as strict as the byte loop (it is the byte loop whenever it
    cannot prove the input is within the caps) and adds no rejection of its own.
    """
    if len(raw) > _SCAN_LIMIT or not _within_caps(raw):
        _byte_caps(raw)


def decode_json(
    raw: bytes,
    *,
    max_bytes: int = 128 * MIB,
    number_decoder: Callable[[str], Any] = exact_number,
) -> Any:
    if len(raw) > max_bytes:
        raise Rejection("decompressed_size_limit")
    _structural_caps(raw)
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
            # Numbers, null and booleans have nothing to check: queue only the rest,
            # in the same order, with C-level iteration.
            if not _CONTAINERS.isdisjoint(map(type, item)):
                pending.extend(compress(item, map(_CONTAINERS.__contains__, map(type, item))))
        elif isinstance(item, dict):
            pending.extend(item.keys())
            values = item.values()
            if not _CONTAINERS.isdisjoint(map(type, values)):
                pending.extend(compress(values, map(_CONTAINERS.__contains__, map(type, values))))
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


def _canonical_pieces(
    content: dict[str, Any], encoder: json.JSONEncoder, remaining: Callable[[], int]
) -> Iterator[str]:
    """C encode each level while retaining the exact sorted JSON byte stream.

    A level is encoded in one C call and yielded whole when it fits every budget (the
    pieces of a fitting level would all pass the same checks). A level that does not
    fit is streamed again, so rejection precedence and the charged used/requested
    bytes at the boundary are those of the streaming encoder. The encoded level is
    allocated before the check; it is bounded by the input level's size.
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
            try:
                encoded = encoder.encode(level)
            except (TypeError, ValueError, RecursionError):
                # Unsupported or non-finite content fails where the stream reaches it,
                # after the budget has charged the pieces before it.
                yield from encoder.iterencode(level)
                continue
            if len(encoded) <= remaining():
                yield encoded
            else:
                yield from encoder.iterencode(level)
        yield "]"
    yield "}"
