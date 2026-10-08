"""Offline micro-experiments behind the performance review's estimates.

Each variant is a scratch measurement, not an implementation: it asserts the
canonical bytes and hashes stay identical to the current encoder on the same
input, then records the timing. No upstream, database or object-store access.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floatchat_core.ingestion import numeric  # noqa: E402
from floatchat_core.ingestion.argovis import map_profile  # noqa: E402
from floatchat_core.ingestion.json_stream import documents  # noqa: E402
from floatchat_core.ingestion.numeric import NUMERIC, CanonicalBudget, decode_json  # noqa: E402
from stage1_perf_profile import synthetic_chunk  # noqa: E402


def bench(results, name, function, repeat=3):
    best = None
    value = None
    for _ in range(repeat):
        started = time.perf_counter()
        value = function()
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    results[name] = round(best, 4)
    return value


def level_pieces_encode_then_check(content, encoder, remaining):
    """Variant A: C-encode each level, keep it if it fits every budget, else stream it."""
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
            encoded = encoder.encode(level)
            if len(encoded) <= remaining():
                yield encoded
            else:
                yield from encoder.iterencode(level)
        yield "]"
    yield "}"


def decimal_only(token):
    """Variant C: strict grammar and length only; no normalized-text preflight."""
    if not NUMERIC.fullmatch(token) or len(token) > 128:
        raise ValueError(token)
    return Decimal(token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=30)
    parser.add_argument("--levels", type=int, default=699)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload, _, metadata = synthetic_chunk(args.profiles, args.levels)
    meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    docs = list(documents(payload))
    profiles = [map_profile(d, meta, CanonicalBudget()) for d in docs]
    contents = [json.loads(p.canonical_bytes) for p in profiles]
    results = {}
    baseline = bench(
        results,
        "encode: current _canonical_pieces (bound walk + C per level)",
        lambda: [CanonicalBudget().encode(c) for c in contents],
    )
    original = numeric._canonical_pieces
    numeric._canonical_pieces = level_pieces_encode_then_check
    try:
        variant = bench(
            results,
            "encode: variant A, C-encode level then length check",
            lambda: [CanonicalBudget().encode(c) for c in contents],
        )
    finally:
        numeric._canonical_pieces = original
    assert variant == baseline, "variant A changed canonical bytes or hashes"
    whole = bench(
        results,
        "encode: variant B, one json.dumps per profile + sha256 (bound on gains)",
        lambda: [
            hashlib.sha256(
                json.dumps(c, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            for c in contents
        ],
    )
    assert whole == [h for _, h in baseline], "variant B changed hashes"
    bench(
        results,
        "decode: current documents() (exact_number with decimal_text preflight)",
        lambda: list(documents(payload)),
    )
    bench(
        results,
        "decode: variant C, Decimal only (no normalized-text preflight)",
        lambda: list(documents(payload, number_decoder=decimal_only)),
    )
    bench(
        results,
        "decode: json.loads with binary floats (lower bound, not contract-conformant)",
        lambda: json.loads(payload),
    )
    bench(
        results,
        "decode: json.loads with parse_float=str/parse_int=str (token capture only)",
        lambda: json.loads(payload, parse_float=str, parse_int=str),
    )
    canonical = sum(len(p.canonical_bytes) for p in profiles)
    report = {
        "kind": "stage1_offline_encoding_experiments",
        "scope": "Scratch variants measured against the current encoder on a synthetic clone "
        "chunk; "
        "byte-identical canonical output asserted; not an implementation or a contract change",
        "profiles": args.profiles,
        "levels_per_profile": args.levels,
        "levels": args.profiles * args.levels,
        "canonical_bytes": canonical,
        "raw_payload_bytes": len(payload),
        "best_of_3_seconds": results,
        "byte_identical": {"variant_A": True, "variant_B_hashes": True},
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, value in results.items():
        print(f"{value:8.3f}s  {name}")


if __name__ == "__main__":
    main()
