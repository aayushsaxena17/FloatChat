"""Bounded live depth spot-check for capacity sizing (ADR-0039 authorization).

Fetches data=all for two dense census leaves outside January and records level
counts per profile, so the canonical-work estimate does not rest on January alone.
Two unretried requests; only counts and checksums are written. Not ingestion,
F01 or acceptance evidence.

Run: scripts/with_argovis_key.sh uv run --all-packages --frozen --offline \
     python -m scripts.stage1_depth_spotcheck --live-opt-in
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

from floatchat_core.ingestion.numeric import MIB, decode_json

from scripts.probe_argovis_empty_semantics import raw_request

ROOT = Path(__file__).resolve().parents[1]
LEAVES = (
    ("2025-02-22T00:00:00Z", "2025-03-01T00:00:00Z", (80, 0)),
    ("2025-03-01T00:00:00Z", "2025-03-08T00:00:00Z", (70, -10)),
)


def polygon(west: int, south: int) -> str:
    from floatchat_core.ingestion.planning import Tile

    return Tile(west, south).polygon()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-opt-in", action="store_true")
    parser.add_argument(
        "--leaf", nargs=4, action="append", metavar=("START", "END", "WEST", "SOUTH")
    )
    parser.add_argument("--output", default="reports/stage1-depth-spotcheck.json")
    args = parser.parse_args()
    leaves = tuple((a, b, (int(w), int(s))) for a, b, w, s in args.leaf) if args.leaf else LEAVES
    credential = os.environ.get("ARGOVIS_API_KEY", "")
    if not args.live_opt_in or not credential:
        print("live_opt_in_and_key_required", file=sys.stderr)
        return 2
    results = []
    for start, end, (west, south) in leaves:
        parameters = {
            "startDate": start,
            "endDate": end,
            "polygon": polygon(west, south),
            "data": "all",
        }
        status, headers, payload, count = raw_request(parameters, credential, raw_limit=16 * MIB)
        if credential.encode() in payload:
            raise SystemExit("credential echoed by upstream; nothing written")
        body = decode_json(payload, max_bytes=128 * MIB)
        levels = []
        for document in body if isinstance(body, list) else []:
            arrays = document.get("data") if isinstance(document, dict) else None
            lengths = {len(a) for a in arrays if isinstance(a, list)} if arrays else set()
            levels.append(next(iter(lengths)) if len(lengths) == 1 else None)
        known = [x for x in levels if x is not None]
        results.append(
            {
                "start": start,
                "end": end,
                "tile": f"{west}:{south}",
                "http_status": status,
                "content_encoding": headers.get("content-encoding"),
                "wire_bytes": count,
                "decoded_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "profiles": len(levels),
                "unknown_level_profiles": len(levels) - len(known),
                "levels_total": sum(known),
                "levels_mean": statistics.fmean(known) if known else None,
                "levels_max": max(known, default=None),
                "levels_min": min(known, default=None),
            }
        )
    all_levels = sum(r["levels_total"] for r in results)
    all_profiles = sum(r["profiles"] - r["unknown_level_profiles"] for r in results)
    report = {
        "kind": "stage1_capacity_depth_spotcheck",
        "authorization": "ADR-0039",
        "scope": "Level-depth sample outside January for capacity sizing only",
        "results": results,
        "levels_per_profile": all_levels / all_profiles if all_profiles else None,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if credential in text:
        raise SystemExit("credential leak guard tripped; nothing written")
    (ROOT / args.output).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
