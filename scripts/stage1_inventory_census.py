"""Inventory-only Jan-Mar 2025 regional census (ADR-0039 authorization).

One inventory request (no data) per planned 1,260-leaf acceptance chunk, through the
same pinned transport primitives as the probe. Counts locally owned profile IDs with
the planner's tile ownership, UTC slice and region rules, and records every 404 body.
Bounded diagnostic retries only for transport errors, 408, 429 and 5xx. This is a
capacity/coverage census, never ingestion, F01 or acceptance evidence: inventories
carry no level counts, so levels are estimated separately from measured averages.

Run: scripts/with_argovis_key.sh uv run --all-packages --frozen --offline \
     python -m scripts.stage1_inventory_census --live-opt-in
"""

import argparse
import collections
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from floatchat_core.ingestion.argovis import request_parameters
from floatchat_core.ingestion.numeric import MIB, Rejection, decode_json
from floatchat_core.ingestion.planning import in_region, month_interval, plan, timestamp

from scripts.probe_argovis_empty_semantics import raw_request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/stage1-inventory-census.json"
RETRYABLE = {408, 429} | set(range(500, 600))


def fetch_inventory(parameters: dict[str, str], credential: str) -> dict[str, object]:
    for attempt in range(1, 5):
        try:
            status, headers, payload, count = raw_request(
                parameters, credential, raw_limit=16 * MIB
            )
        except (Rejection, OSError) as error:
            outcome: dict[str, object] = {"rejection": str(error) or type(error).__name__}
            if attempt < 4:
                time.sleep(2**attempt)
                continue
            return {**outcome, "attempts": attempt}
        if status in RETRYABLE and attempt < 4:
            time.sleep(2**attempt)
            continue
        if credential.encode() in payload:
            raise SystemExit("credential echoed by upstream; nothing written")
        return {
            "status": status,
            "content_type": headers.get("content-type"),
            "payload": payload,
            "bytes": count,
            "attempts": attempt,
        }
    raise AssertionError("unreachable")


def owned_ids(documents: list[object], chunk) -> list[str]:
    result = []
    for document in documents:
        if not isinstance(document, dict):
            raise Rejection("invalid_inventory")
        if not chunk.interval.contains(timestamp(document.get("timestamp", ""))):
            continue
        lon, lat = document["geolocation"]["coordinates"]
        lon, lat = Decimal(str(lon)), Decimal(str(lat))
        if in_region(lon, lat) and chunk.tile.owns(lon, lat):
            result.append(str(document["_id"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-opt-in", action="store_true")
    parser.add_argument("--pause", type=float, default=0.5)
    args = parser.parse_args()
    credential = os.environ.get("ARGOVIS_API_KEY", "")
    if not args.live_opt_in or not credential:
        print("live_opt_in_and_key_required", file=sys.stderr)
        return 2
    chunks = plan(month_interval("2025-01", "2025-03"))
    started = datetime.now(UTC)
    leaves = []
    owners: dict[str, list[str]] = collections.defaultdict(list)
    slot_profiles: collections.Counter[str] = collections.Counter()
    for index, chunk in enumerate(chunks):
        parameters = request_parameters(chunk, inventory=True)
        result = fetch_inventory(parameters, credential)
        leaf: dict[str, object] = {
            "start": parameters["startDate"],
            "end": parameters["endDate"],
            "tile": chunk.tile.key,
            "attempts": result.get("attempts"),
        }
        if "rejection" in result:
            leaf["outcome"] = "failed"
            leaf["reason"] = result["rejection"]
        else:
            payload = result["payload"]
            assert isinstance(payload, bytes)
            leaf["status"] = result["status"]
            leaf["content_type"] = result["content_type"]
            leaf["bytes"] = result["bytes"]
            leaf["sha256"] = hashlib.sha256(payload).hexdigest()
            try:
                body = decode_json(payload, max_bytes=128 * MIB)
            except Rejection as error:
                body, leaf["outcome"], leaf["reason"] = None, "failed", str(error)
            if body is not None:
                if result["status"] == 404 and body == []:
                    leaf["outcome"] = "empty_404"
                    leaf["raw_body_hex"] = payload.hex() if len(payload) <= 64 else None
                elif result["status"] == 200 and isinstance(body, list):
                    ids = owned_ids(body, chunk)
                    leaf["outcome"] = "documents" if body else "empty_200"
                    leaf["documents"] = len(body)
                    leaf["owned_profiles"] = len(ids)
                    for identifier in ids:
                        owners[identifier].append(f"{parameters['startDate']}/{chunk.tile.key}")
                    month = chunk.interval.start.strftime("%Y-%m")
                    slot_profiles[f"{month}/{chunk.tile.west}:{chunk.tile.south}"] += len(ids)
                else:
                    leaf["outcome"] = "unexpected"
                    leaf["reason"] = f"status_{result['status']}_{type(body).__name__}"
        leaves.append(leaf)
        if (index + 1) % 90 == 0:
            done = collections.Counter(str(x["outcome"]) for x in leaves)
            print(f"{index + 1}/{len(chunks)} {dict(done)} profiles={len(owners)}", flush=True)
        time.sleep(args.pause)
    outcomes = collections.Counter(str(x["outcome"]) for x in leaves)
    multiple = {k: v for k, v in owners.items() if len(v) > 1}
    report = {
        "kind": "stage1_jan_mar_2025_inventory_census",
        "authorization": "ADR-0039",
        "scope": "Inventory-only capacity/coverage census; not ingestion or acceptance evidence",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "planned_leaves": len(chunks),
        "outcomes": dict(outcomes),
        "unique_owned_profiles": len(owners),
        "ids_owned_by_multiple_leaves": len(multiple),
        "slot_profiles": dict(sorted(slot_profiles.items())),
        "max_slot_profiles": max(slot_profiles.values(), default=0),
        "max_leaf_owned_profiles": max(
            (int(x.get("owned_profiles", 0)) for x in leaves), default=0
        ),
        "leaves": leaves,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if credential in text:
        raise SystemExit("credential leak guard tripped; nothing written")
    OUT.write_text(text)
    print(json.dumps({k: v for k, v in report.items() if k not in ("leaves", "slot_profiles")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
