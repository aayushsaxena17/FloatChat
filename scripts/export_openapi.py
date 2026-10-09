"""Write the FastAPI schema to ``apps/api/openapi.json`` (plan W4/W5).

    uv run --all-packages --frozen python scripts/export_openapi.py          # rewrite the file
    uv run --all-packages --frozen python scripts/export_openapi.py --check  # exit 1 on drift

The committed file feeds the generated TypeScript client; CI fails when it differs from the live
application, so an API change always ships its regenerated schema.
"""

import argparse
import json
import sys
from pathlib import Path

from floatchat_api.main import create_app

OUTPUT = Path(__file__).resolve().parents[1] / "apps/api/openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when the committed file differs"
    )
    arguments = parser.parse_args()
    expected = render()
    if arguments.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current != expected:
            print(f"{OUTPUT.relative_to(OUTPUT.parents[2])} is out of date; run this script")
            return 1
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
