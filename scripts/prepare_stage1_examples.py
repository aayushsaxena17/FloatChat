"""Offline extraction of attributed published notebook outputs, never a live capture.

Input is the pinned official notebook downloaded separately during cache preparation.
No notebook cell executes. Python display literals are parsed with literal_eval only.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path

COMMIT = "3e3307c878a61483cc6c31010dd857f7f7d5251c"
SOURCE = f"https://github.com/argovis/demo_notebooks/blob/{COMMIT}/introduction/Argovis_JSON.ipynb"


def prepare(notebook: Path, output: Path) -> None:
    raw = notebook.read_bytes()
    cells = json.loads(raw)["cells"]
    examples = {
        "published_inventory_profile.json": [
            ast.literal_eval("".join(cells[12]["outputs"][0]["data"]["text/plain"]))
        ],
        "published_metadata.json": ast.literal_eval(
            "".join(cells[14]["outputs"][1]["data"]["text/plain"])
        ),
        "published_temperature_pressure_arrays.json": ast.literal_eval(
            "".join(cells[24]["outputs"][0]["text"]).split("\n", 1)[1]
        ),
        "published_data_info.json": ast.literal_eval("".join(cells[26]["outputs"][0]["text"])),
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "published_examples_not_live_raw_capture",
        "source_url": SOURCE,
        "source_commit": COMMIT,
        "notebook_sha256": hashlib.sha256(raw).hexdigest(),
        "upstream_capture_time": None,
        "original_http_response_sha256": None,
        "specification": "2.36.2",
        "mapping": "argovis-core-v1",
        "attribution": "Argovis Collaboration; Argo GDAC dataset DOI 10.17882/42182",
        "sanitization": "Only listed public display outputs extracted; no code/config/headers.",
        "limitation": "Arrays refer to 4901283_003; inventory/metadata to 1901094_109. "
        "Do not combine them as matching recorded responses. F01 pending.",
        "files": {},
    }
    for name, value in examples.items():
        data = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
        (output / name).write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.notebook, args.output)
