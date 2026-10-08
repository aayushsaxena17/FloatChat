"""Bounded live probe of Argovis empty-selection semantics (ADR-0039 authorization).

Issues at most seven sequential GET /argo requests through the production pinned,
validated transport primitives, with no retries, and records for every response:
status, content type, framing headers, byte counts, SHA-256 and, for small non-200
or empty bodies, the complete sanitized body. Inventory responses with documents
record only their count. Never ingestion, F01 or acceptance evidence.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from floatchat_core.ingestion.numeric import MIB, Rejection, decode_json
from floatchat_core.ingestion.planning import Tile
from floatchat_core.ingestion.raw import sanitize_raw
from floatchat_core.ingestion.transport import (
    BASE,
    HOST,
    PinnedConnection,
    operation_deadline,
    public_addresses,
    read_body,
    validate_endpoint,
)

ROOT = Path(__file__).resolve().parents[1]
WEEK = {"startDate": "2025-01-01T00:00:00Z", "endDate": "2025-01-08T00:00:00Z"}
# (label, tile, roles): two of the 44 historical 404 selections plus one control
# tile that published 45 profiles in the original run.
SELECTIONS = (
    ("historical_404_land_20_0", Tile(20, 0), ("inventory_before", "profile", "inventory_after")),
    (
        "historical_404_coastal_100_10",
        Tile(100, 10),
        ("inventory_before", "profile", "inventory_after"),
    ),
    ("control_published_70_-10", Tile(70, -10), ("inventory_before",)),
)
SMALL_BODY = 4096


def raw_request(
    parameters: dict[str, str], credential: str, *, raw_limit: int = MIB
) -> tuple[int, dict[str, str], bytes, int]:
    """One unretried GET /argo; returns status, framing headers, body and wire bytes."""
    validate_endpoint(BASE + "/argo")
    deadline = time.monotonic() + 120
    received = 0

    def account(amount: int) -> None:
        nonlocal received
        received += amount

    connection = None
    try:
        with operation_deadline(min(deadline, time.monotonic() + 10)):
            connection = PinnedConnection(public_addresses()[0], 10)
            connection.connect()
        with operation_deadline(deadline):
            assert connection.sock is not None
            connection.sock.settimeout(20)
            connection.request(
                "GET",
                "/argo?" + urlencode(parameters),
                headers={
                    "Host": HOST,
                    "x-argokey": credential,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = {
                key.lower(): value
                for key, value in response.getheaders()
                if key.lower()
                in ("content-type", "content-encoding", "content-length", "transfer-encoding")
            }
            if 300 <= response.status <= 399:
                raise Rejection("upstream_redirect_rejected")
            payload, count = read_body(
                response, account, raw_limit=raw_limit, json_limit=8 * raw_limit
            )
            return response.status, headers, payload, count
    finally:
        if connection is not None:
            connection.close()


def get(parameters: dict[str, str], credential: str) -> dict[str, object]:
    status, headers, payload, count = raw_request(parameters, credential)
    clean = sanitize_raw(payload, credential).payload
    if credential.encode() in clean:
        raise Rejection("credential_in_sanitized_body")
    record: dict[str, object] = {
        "http_status": status,
        "headers": headers,
        "received_bytes": count,
        "decoded_bytes": len(payload),
        "sha256": hashlib.sha256(clean).hexdigest(),
    }
    if len(payload) <= 64 and credential.encode() not in payload:
        record["raw_body_hex"] = payload.hex()
    try:
        body = decode_json(clean, max_bytes=8 * MIB)
    except Rejection as error:
        record["json"] = f"invalid:{error}"
        return record
    if isinstance(body, list) and body and status == 200:
        record["json"] = {"type": "array", "documents": len(body)}
    elif len(clean) <= SMALL_BODY:
        record["json"] = {"type": type(body).__name__, "body": clean.decode("utf-8")}
    else:
        record["json"] = {"type": type(body).__name__, "large": True}
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-opt-in", action="store_true")
    args = parser.parse_args()
    if not args.live_opt_in:
        print("live_opt_in_required", file=sys.stderr)
        return 2
    credential = os.environ.get("ARGOVIS_API_KEY", "")
    if not credential:
        print("ARGOVIS_API_KEY missing", file=sys.stderr)
        return 2
    results = []
    for label, tile, roles in SELECTIONS:
        for role in roles:
            parameters = {**WEEK, "polygon": tile.polygon()}
            if role == "profile":
                parameters["data"] = "all"
            started = datetime.now(UTC)
            try:
                outcome = get(parameters, credential)
            except Rejection as error:
                outcome = {"rejection": str(error)}
            except OSError:
                outcome = {"rejection": "upstream_transport_failure"}
            results.append(
                {
                    "selection": label,
                    "tile": tile.key,
                    "role": role,
                    "parameters": parameters,
                    "requested_at_utc": started.isoformat(),
                    **outcome,
                }
            )
            time.sleep(1)
    report = {
        "kind": "argovis_live_empty_selection_probe",
        "authorization": "ADR-0039",
        "scope": "Diagnostic HTTP semantics only; not ingestion, F01 or acceptance evidence",
        "endpoint": BASE + "/argo",
        "requests": len(results),
        "results": results,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if credential in text:
        raise SystemExit("credential leak guard tripped; nothing written")
    out = ROOT / "reports/stage1-live-empty-semantics.json"
    out.write_text(text)
    for row in results:
        print(row["selection"], row["role"], row.get("http_status"), json.dumps(row.get("json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
