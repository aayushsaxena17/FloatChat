"""Local acceptance storage initialization, including an empty denied control bucket."""

import os
import sys

from bootstrap_storage import main, run

if __name__ == "__main__":
    try:
        main()
        control = os.environ["ACCEPTANCE_CONTROL_BUCKET"]
        if not control.startswith("floatchat-s1-acceptance-") or not control.endswith("-control"):
            raise ValueError("invalid_local_control_bucket")
        run("mb", "--ignore-existing", "local/" + control)
        run("anonymous", "set", "none", "local/" + control)
        print("isolated_acceptance_storage_initialized")
    except Exception:
        print("acceptance_storage_failed_no_sensitive_diagnostics", file=sys.stderr)
        raise SystemExit(5) from None
