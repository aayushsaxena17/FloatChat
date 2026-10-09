"""Offline benchmark of the stage1-v4 exact decode, sanitization and encoder (package A).

Runs the pre-v4 implementation (vendored below, copied from the tree at 272508b) and the
current one on the same synthetic clone chunk, in the same process, interleaved, and
asserts the outputs are identical before it records a timing. It also carries the
reference lower bounds of reports/stage1-perf-experiments.json (the offline measurements
behind docs/ingestion-performance-review.md section 3.3) and reprints that file's recorded
numbers next to the fresh ones. No upstream, database or object-store access.
"""

import argparse
import gc
import hashlib
import json
import math
import platform
import re
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floatchat_core.ingestion import numeric  # noqa: E402
from floatchat_core.ingestion.argovis import map_profile, sanitize_source_url  # noqa: E402
from floatchat_core.ingestion.json_stream import documents  # noqa: E402
from floatchat_core.ingestion.numeric import (  # noqa: E402
    MIB,
    NUMERIC,
    CanonicalBudget,
    Rejection,
    decimal_text,
    decode_json,
    exact_number,
)
from floatchat_core.ingestion.raw import sanitize_raw  # noqa: E402
from stage1_perf_profile import synthetic_chunk  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# --- pre-v4 implementation, vendored (do not edit: it is the "before") ------------------


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
    legacy_decimal_text(value)  # Preflight before any exponent-free allocation.
    return value


def legacy_prepass(raw):
    depth = 0
    quoted = escaped = False
    string_size = 0
    arrays = []  # opening delimiter, count, current element seen
    for byte in raw:
        if quoted:
            string_size += 1
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


def legacy_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejection("duplicate_json_key")
        result[key] = value
    return result


def legacy_decode_json(raw, *, number_decoder=legacy_exact_number):
    if len(raw) > 128 * MIB:
        raise Rejection("decompressed_size_limit")
    legacy_prepass(raw)
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


def legacy_documents(raw, *, max_documents=2000, number_decoder=legacy_exact_number):
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
        value = legacy_decode_json(raw[first:cursor], number_decoder=number_decoder)
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


SECRET_FIELD = re.compile(
    r"(?:authorization|api[_-]?key|argo[_-]?key|password|secret|credential|token)", re.I
)


class LegacyRawNumber(Decimal):
    source_token: str

    def __new__(cls, token):
        legacy_exact_number(token)
        instance = super().__new__(cls, token)
        instance.source_token = token
        return instance


def legacy_sanitize_raw(raw, credential=None):
    is_array = raw.lstrip().startswith(b"[")
    document = None if is_array else legacy_decode_json(raw, number_decoder=LegacyRawNumber)
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
        if len(output) + len(encoded) > 128 * MIB:
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
        for index, item in enumerate(legacy_documents(raw, number_decoder=LegacyRawNumber)):
            if index:
                write(",")
            encode(clean(item))
        write("]")
    else:
        encode(clean(document))
    return bytes(output), {"version": "raw-sanitization-v1", **counters}


def small_json_bound(value):
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


def legacy_canonical_pieces(content, encoder, remaining) -> Iterator[str]:
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
            bound = small_json_bound(level)
            if bound is not None and bound <= remaining():
                yield encoder.encode(level)
            else:
                yield from encoder.iterencode(level)
        yield "]"
    yield "}"


def legacy_encode_all(contents):
    original = numeric._canonical_pieces
    numeric._canonical_pieces = legacy_canonical_pieces
    try:
        return [CanonicalBudget().encode(content) for content in contents]
    finally:
        numeric._canonical_pieces = original


# --- measurement -----------------------------------------------------------------------


def decimal_only(token):
    """Reference: strict grammar and length only; no normalized-text preflight."""
    if not NUMERIC.fullmatch(token) or len(token) > 128:
        raise ValueError(token)
    return Decimal(token)


def best_of(functions, repeat):
    """Best wall and CPU seconds of each function, interleaved so host noise is shared."""
    best = {name: [None, None] for name in functions}
    value = {}
    for _ in range(repeat):
        for name, function in functions.items():
            gc.collect()  # Every timed run starts from a clean heap, whatever ran before it.
            wall, cpu = time.perf_counter(), time.process_time()
            value[name] = function()
            wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
            current = best[name]
            current[0] = wall if current[0] is None else min(current[0], wall)
            current[1] = cpu if current[1] is None else min(current[1], cpu)
    return {name: (round(w, 4), round(c, 4)) for name, (w, c) in best.items()}, value


def compare(results, name, legacy, current, repeat, same):
    timing, value = best_of({"pre_v4": legacy, "v4": current}, repeat)
    assert same(value["pre_v4"], value["v4"]), f"{name}: v4 output differs from pre-v4"
    (old_wall, old_cpu), (new_wall, new_cpu) = timing["pre_v4"], timing["v4"]
    results[name] = {
        "pre_v4_wall_s": old_wall,
        "v4_wall_s": new_wall,
        "speedup_wall": round(old_wall / new_wall, 2) if new_wall else None,
        "pre_v4_cpu_s": old_cpu,
        "v4_cpu_s": new_cpu,
        "speedup_cpu": round(old_cpu / new_cpu, 2) if new_cpu else None,
        "output_identical": True,
    }


def reference(results, name, function, repeat):
    timing, _ = best_of({name: function}, repeat)
    results[name] = {"wall_s": timing[name][0], "cpu_s": timing[name][1]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=30)
    parser.add_argument("--levels", type=int, default=699)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "reports/stage1-perf-experiments.json"
    )
    args = parser.parse_args()
    payload, _, metadata = synthetic_chunk(args.profiles, args.levels)
    meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    docs = list(documents(payload))
    profiles = [map_profile(d, meta, CanonicalBudget()) for d in docs]
    contents = [json.loads(p.canonical_bytes) for p in profiles]
    first_document = json.dumps(json.loads(payload)[0], separators=(",", ":")).encode()
    tokens = []

    def collect(token):
        tokens.append(token)
        return token

    json.loads(payload, parse_float=collect, parse_int=collect)
    results = {}
    repeat = args.repeat

    compare(
        results,
        "encode: CanonicalBudget.encode over all profiles",
        lambda: legacy_encode_all(contents),
        lambda: [CanonicalBudget().encode(c) for c in contents],
        repeat,
        lambda a, b: a == b,
    )
    compare(
        results,
        "decode: exact_number per number token",
        lambda: [legacy_exact_number(t) for t in tokens],
        lambda: [exact_number(t) for t in tokens],
        repeat,
        lambda a, b: [x.as_tuple() for x in a] == [x.as_tuple() for x in b],
    )
    values = [exact_number(token) for token in tokens]
    compare(
        results,
        "normalize: decimal_text per number (scientific_number calls it once per number)",
        lambda: [legacy_decimal_text(v) for v in values],
        lambda: [decimal_text(v) for v in values],
        repeat,
        lambda a, b: repr(a) == repr(b),
    )
    compare(
        results,
        "decode: structural scan of the whole payload (depth/array/string caps)",
        lambda: legacy_prepass(payload),
        lambda: numeric._structural_caps(payload),
        repeat,
        lambda a, b: a is None and b is None,
    )
    compare(
        results,
        "decode: decode_json of one profile document",
        lambda: legacy_decode_json(first_document),
        lambda: decode_json(first_document),
        repeat,
        lambda a, b: repr(a) == repr(b),
    )
    compare(
        results,
        "decode: documents() over the payload",
        lambda: list(legacy_documents(payload)),
        lambda: list(documents(payload)),
        repeat,
        lambda a, b: repr(a) == repr(b),
    )
    compare(
        results,
        "sanitize_raw(profile payload)",
        lambda: legacy_sanitize_raw(payload),
        lambda: (lambda r: (r.payload, r.manifest))(sanitize_raw(payload)),
        repeat,
        lambda a, b: a == b,
    )
    assert sanitize_raw(payload).payload == payload  # The clone chunk is a fixed point.

    references = {}
    reference(
        references,
        "decode: Decimal only, no normalized-text preflight (recorded 'variant C')",
        lambda: list(documents(payload, number_decoder=decimal_only)),
        repeat,
    )
    reference(
        references,
        "decode: json.loads with parse_float=str/parse_int=str (token capture only)",
        lambda: json.loads(payload, parse_float=str, parse_int=str),
        repeat,
    )
    reference(
        references,
        "encode: one json.dumps per profile + sha256 (recorded 'variant B', bound on gains)",
        lambda: [
            hashlib.sha256(
                json.dumps(c, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            for c in contents
        ],
        repeat,
    )

    recorded = json.loads(args.baseline.read_text())["best_of_3_seconds"]
    pairs = {
        "encode: CanonicalBudget.encode over all profiles": (
            "encode: current _canonical_pieces (bound walk + C per level)",
            "encode: variant A, C-encode level then length check",
        ),
        "decode: documents() over the payload": (
            "decode: current documents() (exact_number with decimal_text preflight)",
            "decode: variant C, Decimal only (no normalized-text preflight)",
        ),
    }
    versus_recorded = {}
    for name, (current_key, variant_key) in pairs.items():
        versus_recorded[name] = {
            "recorded_current_s": recorded[current_key],
            "recorded_prototype_s": recorded[variant_key],
            "measured_pre_v4_wall_s": results[name]["pre_v4_wall_s"],
            "measured_v4_wall_s": results[name]["v4_wall_s"],
        }
    report = {
        "kind": "stage1_v4_package_a_bench",
        "scope": "Exact decode, sanitize_raw and canonical encoder: the pre-v4 implementation "
        "(vendored in the script, copied from 272508b) against the current tree on a synthetic "
        "clone chunk; outputs asserted identical; best of N interleaved runs; no network, "
        "database or object store",
        "profiles": args.profiles,
        "levels_per_profile": args.levels,
        "levels": args.profiles * args.levels,
        "number_tokens": len(tokens),
        "canonical_bytes": sum(len(p.canonical_bytes) for p in profiles),
        "raw_payload_bytes": len(payload),
        "repeat": repeat,
        "results": results,
        "reference_lower_bounds": references,
        "recorded_baseline_file": str(args.baseline.relative_to(ROOT))
        if args.baseline.is_relative_to(ROOT)
        else str(args.baseline),
        "versus_recorded_baseline": versus_recorded,
        "host": {"python": platform.python_version(), "machine": platform.machine()},
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, row in results.items():
        print(
            f"{row['pre_v4_wall_s']:8.3f}s -> {row['v4_wall_s']:8.3f}s  "
            f"x{row['speedup_wall']:<6} (cpu x{row['speedup_cpu']})  {name}"
        )
    for name, row in references.items():
        print(f"{row['wall_s']:8.3f}s  reference: {name}")


if __name__ == "__main__":
    main()
