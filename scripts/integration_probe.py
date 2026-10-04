"""Runs only inside the disposable integration project's API container."""

import sys
import urllib.error
import urllib.request
import uuid

import psycopg
from floatchat_api.health import storage_client
from floatchat_core.config import Settings
from floatchat_workers.app import app


def main() -> None:
    settings = Settings()
    mode = sys.argv[1]
    client = storage_client(settings)
    bucket = settings.object_storage_bucket
    try:
        if mode == "seed":
            client.put_object(Bucket=bucket, Key="stage0-persistence", Body=b"preserved")
        elif mode == "verify":
            assert (
                client.get_object(Bucket=bucket, Key="stage0-persistence")["Body"].read()
                == b"preserved"
            )
            key = "smoke/" + uuid.uuid4().hex
            client.put_object(Bucket=bucket, Key=key, Body=b"local")
            assert client.get_object(Bucket=bucket, Key=key)["Body"].read() == b"local"
            client.delete_object(Bucket=bucket, Key=key)
            with psycopg.connect(settings.database_url.get_secret_value()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT value FROM stage0_persistence")
                    assert cursor.fetchone() == ("preserved",)
        elif mode == "anonymous":
            url = settings.object_storage_endpoint + "/" + bucket + "/stage0-persistence"
            try:
                urllib.request.urlopen(url, timeout=5)
                raise AssertionError("anonymous object access allowed")
            except urllib.error.HTTPError as error:
                assert error.code == 403
        elif mode == "worker":
            result = app.send_task("floatchat.smoke", args=["stage0"])
            assert result.get(timeout=30) == "ok:stage0"
        elif mode in ["invalid-storage", "missing-bucket"]:
            import asyncio

            from floatchat_api.health import dependency_checks, ready

            if mode == "invalid-storage":
                settings = settings.model_copy(
                    update={
                        "object_storage_secret_key": settings.object_storage_secret_key.__class__(
                            "invalid"
                        )
                    }
                )
            else:
                settings = settings.model_copy(
                    update={"object_storage_bucket": "missing-" + uuid.uuid4().hex}
                )
            assert not asyncio.run(ready(dependency_checks(settings), 4))
        else:
            raise ValueError("unknown integration probe")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
        print("Integration probe passed.")
    except Exception:
        print("Integration probe failed; sensitive diagnostics suppressed.", file=sys.stderr)
        raise SystemExit(1) from None
