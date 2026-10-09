"""Download and store the offline GDAC fixtures (tests/fixtures/gdac).

Network: https://data-argo.ifremer.fr only (anonymous, HTTPS, no redirects, 128 MiB per
file), through floatchat_core.ingestion.gdac.fetch_file. Run once:

    .venv/bin/python scripts/gdac_fixtures.py
"""

import gzip
import hashlib
import io
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion.gdac import ATTRIBUTION, GDAC_HOST, INDEX_KEY, fetch_file

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/fixtures/gdac"
EXCERPT = "ar_index_indian_2025q1.txt"
LISTING = "geo/indian_ocean/2025/01/"
DAILY = ("geo/indian_ocean/2025/01/20250115_prof.nc", "geo/indian_ocean/2025/02/20250214_prof.nc")
DAILY_LIMIT = 8 * 1024 * 1024
TOTAL_LIMIT = 12 * 1024 * 1024
BOX = (-60.0, 30.0, 20.0, 120.0)  # south, north, west, east
WINDOW = ("20250101000000", "20250331235959")


def excerpt(raw_gz: bytes) -> bytes:
    """Stream the decompressed index; keep comments, header and rows inside BOX/WINDOW."""
    south, north, west, east = BOX
    kept = []
    total = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw_gz)) as stream:
        for line in stream:
            total += 1
            text = line.decode("ascii")
            if text.startswith("#") or text.startswith("file,"):
                kept.append(text)
                continue
            fields = text.rstrip("\n").split(",")
            if len(fields) != 8 or not (fields[1] and fields[2] and fields[3]):
                continue
            date, latitude, longitude = fields[1], float(fields[2]), float(fields[3])
            if (
                WINDOW[0] <= date <= WINDOW[1]
                and south <= latitude <= north
                and west <= longitude <= east
            ):
                kept.append(text)
    print(f"index lines read: {total}; kept (with header): {len(kept)}")
    return "".join(kept).encode("ascii")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 4 * 3600
    listing = fetch_file(LISTING, deadline, max_bytes=2 * 1024 * 1024).decode("utf-8", "replace")
    names = re.findall(r'href="(\d{8}_prof\.nc)"[^\n]*', listing)
    print(f"listing {LISTING}: {len(names)} daily files; sample lines:")
    for line in [x for x in listing.splitlines() if "_prof.nc" in x][:3]:
        print("  " + line.strip()[:200])
    manifest: dict[str, object] = {"attribution": ATTRIBUTION, "host": GDAC_HOST, "files": []}
    files = manifest["files"]
    assert isinstance(files, list)
    total = 0

    for key in DAILY:
        retrieved = datetime.now(UTC)
        payload = fetch_file(key, deadline, max_bytes=DAILY_LIMIT, attempt_seconds=1800)
        name = key.rsplit("/", 1)[1]
        (OUT / name).write_bytes(payload)
        total += len(payload)
        files.append(
            {
                "path": name,
                "url": f"https://{GDAC_HOST}/{key}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "retrieved_at_utc": retrieved.isoformat(timespec="seconds"),
            }
        )
        print(f"stored {name}: {len(payload)} bytes")
    retrieved = datetime.now(UTC)
    index_gz = fetch_file(INDEX_KEY, deadline, attempt_seconds=7200)
    data = excerpt(index_gz)
    (OUT / EXCERPT).write_bytes(data)
    total += len(data)
    files.append(
        {
            "path": EXCERPT,
            "url": f"https://{GDAC_HOST}/{INDEX_KEY}",
            "derived": "latitude [-60,30], longitude [20,120], date 2025-01-01..2025-03-31",
            "source_sha256": hashlib.sha256(index_gz).hexdigest(),
            "source_bytes": len(index_gz),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "retrieved_at_utc": retrieved.isoformat(timespec="seconds"),
        }
    )
    print(f"stored {EXCERPT}: {len(data)} bytes, {data.count(b'\n')} lines")

    if total > TOTAL_LIMIT:
        print(f"fixture total {total} exceeds {TOTAL_LIMIT}", file=sys.stderr)
        return 1
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"total fixture bytes: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
