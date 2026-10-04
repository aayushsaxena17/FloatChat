"""Private bucket and scoped application identity; admin values never enter the API."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str) -> None:
    subprocess.run(
        ["mc", "--config-dir", "/tmp/floatchat-mc", *args],
        check=True,
        capture_output=True,
        timeout=20,
    )


def main() -> None:
    bucket = os.environ["OBJECT_STORAGE_BUCKET"]
    user = os.environ["OBJECT_STORAGE_ACCESS_KEY"]
    run(
        "alias",
        "set",
        "local",
        os.environ["OBJECT_STORAGE_ENDPOINT"],
        os.environ["MINIO_ROOT_USER"],
        os.environ["MINIO_ROOT_PASSWORD"],
    )
    run("mb", "--ignore-existing", f"local/{bucket}")
    run("anonymous", "set", "none", f"local/{bucket}")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "policy.json"
        path.write_text(json.dumps(policy))
        run("admin", "policy", "create", "local", "floatchat-app", str(path))
    run("admin", "user", "add", "local", user, os.environ["OBJECT_STORAGE_SECRET_KEY"])
    run("admin", "policy", "attach", "local", "floatchat-app", "--user", user)


if __name__ == "__main__":
    try:
        main()
        print("Storage initialization complete.")
    except Exception:
        print("Storage initialization failed; no sensitive diagnostics emitted.", file=sys.stderr)
        raise SystemExit(1) from None
