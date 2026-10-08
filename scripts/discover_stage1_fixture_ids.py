"""Owner-only, one-request inventory discovery; never ingestion or F01 acceptance.

Fixed 5-by-5-degree Indian Ocean selection for one week. No retry, expansion,
profile fetch, metadata fetch, database connection or catalogue write occurs.
Originals are private; only sanitized, scanned inventory evidence is copied.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion.numeric import MIB, Rejection, decode_json
from floatchat_core.ingestion.raw import sanitize_raw
from floatchat_core.ingestion.transport import BASE, HTTPFailure, fetch, retry_after_seconds

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "startDate": "2026-09-28T00:00:00Z",
    "endDate": "2026-10-05T00:00:00Z",
    "polygon": "[[65,-5],[70,-5],[70,0],[65,0],[65,-5]]",
}
MAX_DOCUMENTS = 20


class SafeDiscoveryHTTPDiagnostic(Rejection):
    def __init__(self, failure: HTTPFailure) -> None:
        super().__init__("upstream_http_status")
        if type(failure.status) is not int or not 100 <= failure.status <= 599:
            raise Rejection("upstream_http_status") from None
        self.evidence: dict[str, str | int | float] = {
            "category": "upstream_http_status",
            "http_status": failure.status,
            "request_role": "inventory_discovery",
        }
        if failure.status == 429 and isinstance(failure.retry_after, str):
            try:
                duration = retry_after_seconds(failure.retry_after, datetime.now(UTC))
            except Rejection:
                pass
            else:
                self.evidence["retry_after_seconds"] = duration


def discover(*, opted_in: bool) -> Path:
    if not opted_in:
        raise Rejection("live_capture_opt_in_required")
    credential = os.environ.get("ARGOVIS_API_KEY")
    if not credential:
        raise Rejection("ARGOVIS_API_KEY")
    scanner = ROOT / ".cache/tools/gitleaks"
    if not scanner.is_file():
        raise Rejection("prepare_pinned_secret_scanner_separately")
    capture_id = uuid.uuid4().hex
    private = Path.home() / "private/argovis-captures" / capture_id
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    originals, sanitized = private / "originals", private / "sanitized"
    originals.mkdir(mode=0o700)
    sanitized.mkdir(mode=0o700)
    received = 0

    def account(amount: int) -> None:
        nonlocal received
        received += amount
        if received > MIB:
            raise Rejection("small_discovery_total_size_limit")

    try:
        response = fetch(
            "/argo",
            dict(PARAMETERS),
            credential,
            account,
            deadline=time.monotonic() + 120,
            enabled=lambda: True,
            raw_limit=MIB,
            json_limit=8 * MIB,
        )
    except HTTPFailure as failure:
        raise SafeDiscoveryHTTPDiagnostic(failure) from None
    original = originals / "01-inventory_discovery.json"
    original.write_bytes(response.payload)
    original.chmod(0o600)
    original_manifest = originals / "manifest.json"
    original_manifest.write_text(
        json.dumps(
            {
                "representation": "original_decompressed_json",
                "sha256": hashlib.sha256(response.payload).hexdigest(),
                "bytes": len(response.payload),
                "retrieved_at_utc": response.retrieved_at.isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    original_manifest.chmod(0o600)
    clean = sanitize_raw(response.payload, credential)
    rows = decode_json(clean.payload, max_bytes=8 * MIB)
    if not isinstance(rows, list) or len(rows) > MAX_DOCUMENTS:
        raise Rejection("discovery_inventory_document_limit")
    identifiers = []
    for row in rows:
        if not isinstance(row, dict):
            raise Rejection("discovery_invalid_inventory")
        identifier = row.get("_id")
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,128}", identifier
        ):
            raise Rejection("discovery_invalid_profile_id")
        if identifier in identifiers or "data" in row:
            raise Rejection("discovery_duplicate_or_unexpected_scientific_data")
        identifiers.append(identifier)
    inventory = sanitized / "01-inventory_discovery.json"
    inventory.write_bytes(clean.payload)
    inventory.chmod(0o600)
    specification = ROOT / "docs/upstream/argovis-2.36.2.json"
    manifest = {
        "capture_id": capture_id,
        "kind": "live_recorded_argovis_inventory_discovery",
        "scope": "candidate_discovery_only_not_F01_or_regional_coverage",
        "endpoint": BASE + "/argo",
        "request_parameters": dict(PARAMETERS),
        "request_role": "inventory_discovery",
        "status": 200,
        "retrieved_at_utc": response.retrieved_at.isoformat(),
        "specification": {
            "release": "2.36.2",
            "sha256": hashlib.sha256(specification.read_bytes()).hexdigest(),
            "url": "https://github.com/argovis/argovis_api/blob/2.36.2/core-spec.json",
        },
        "response": {
            "path": inventory.name,
            "representation": "sanitized_decompressed_json",
            "sha256": hashlib.sha256(clean.payload).hexdigest(),
            "bytes": len(clean.payload),
            "received_compressed_bytes": response.received_bytes,
            "sanitization": clean.manifest,
        },
        "candidate_ids": identifiers,
        "candidate_count": len(identifiers),
        "bounds": {
            "requests": 1,
            "concurrency": 1,
            "automatic_retries": 0,
            "compressed_bytes": MIB,
            "decompressed_bytes": 8 * MIB,
            "inventory_documents": MAX_DOCUMENTS,
            "http_seconds": 120,
            "scanner_seconds": 60,
            "owner_command_seconds": 300,
        },
        "attribution": {
            "provider": "International Argo Program and national contributors, via Argovis",
            "argo_doi": "https://doi.org/10.17882/42182",
            "terms_and_acknowledgement": "https://argo.ucsd.edu/data/acknowledging-argo/",
            "argovis_contract_citation": "https://zenodo.org/records/15708506",
        },
        "acceptance": "No regional completeness, empty coverage or F01 representation pass. "
        "Candidate IDs require a later separately selected inventory/profile/metadata capture.",
    }
    manifest_path = sanitized / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    manifest_path.chmod(0o600)
    scan = subprocess.run(
        [
            str(scanner),
            "dir",
            str(sanitized),
            "--redact=100",
            "--no-banner",
            "--max-decode-depth=3",
            "--config",
            str(ROOT / ".gitleaks.toml"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    if scan.returncode != 0:
        raise Rejection("sanitized_capture_secret_scan_failed")
    destination = ROOT / "tests/fixtures/argovis/discovery" / capture_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(sanitized, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-opt-in", action="store_true")
    args = parser.parse_args()
    try:
        destination = discover(opted_in=args.live_opt_in)
        print("Sanitized, scanned discovery bundle: " + str(destination.relative_to(ROOT)))
        return 0
    except SafeDiscoveryHTTPDiagnostic as error:
        print(json.dumps(error.evidence, sort_keys=True))
        return 2
    except Rejection as error:
        print(error.category)
        return 2
    except Exception:
        print("capture_failed_no_sensitive_diagnostics")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
