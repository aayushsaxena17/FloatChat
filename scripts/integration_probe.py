"""Runs only inside the disposable integration project's API container."""

import sys
import urllib.error
import urllib.request
import uuid

import psycopg
from floatchat_api.health import storage_client
from floatchat_core.config import Settings


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
                    cursor.execute("SELECT value FROM app.stage0_persistence")
                    assert cursor.fetchone() == ("preserved",)
        elif mode == "permissions":
            with psycopg.connect(
                settings.database_url.get_secret_value(), autocommit=True
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO app.stage0_permissions(value) VALUES ('initial') RETURNING id"
                    )
                    row_id = cursor.fetchone()[0]
                    cursor.execute(
                        "UPDATE app.stage0_permissions SET value = 'updated' WHERE id = %s",
                        (row_id,),
                    )
                    cursor.execute(
                        "SELECT value FROM app.stage0_permissions WHERE id = %s", (row_id,)
                    )
                    assert cursor.fetchone() == ("updated",)
                    cursor.execute("DELETE FROM app.stage0_permissions WHERE id = %s", (row_id,))
                    assert cursor.rowcount == 1
                    cursor.execute("SELECT count(*) FROM public.spatial_ref_sys")
                    assert cursor.fetchone()[0] > 0
                    cursor.execute(
                        "SELECT count(*) FROM pg_class c JOIN pg_depend d "
                        "ON d.classid = 'pg_class'::regclass AND d.objid = c.oid "
                        "WHERE d.refclassid = 'pg_extension'::regclass AND d.deptype = 'e' "
                        "AND c.relkind IN ('r','p','v','m','f') "
                        "AND has_table_privilege(current_user, c.oid, "
                        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
                    )
                    assert cursor.fetchone() == (0,)
                    for privilege in [
                        "INSERT",
                        "UPDATE",
                        "DELETE",
                        "TRUNCATE",
                        "REFERENCES",
                        "TRIGGER",
                    ]:
                        cursor.execute(
                            "SELECT has_table_privilege("
                            "current_user, 'public.spatial_ref_sys', %s)",
                            (privilege,),
                        )
                        assert cursor.fetchone() == (False,)
                    statements = [
                        "INSERT INTO public.spatial_ref_sys(srid) SELECT 999999 WHERE false",
                        "UPDATE public.spatial_ref_sys SET srtext=srtext WHERE false",
                        "DELETE FROM public.spatial_ref_sys WHERE false",
                    ]
                    for statement in statements:
                        try:
                            cursor.execute(statement)
                        except psycopg.errors.InsufficientPrivilege:
                            pass
                        else:
                            raise AssertionError("Extension metadata write was allowed")
        elif mode == "anonymous":
            url = settings.object_storage_endpoint + "/" + bucket + "/stage0-persistence"
            try:
                urllib.request.urlopen(url, timeout=5)
                raise AssertionError("anonymous object access allowed")
            except urllib.error.HTTPError as error:
                assert error.code == 403
        elif mode == "readiness-deadline":
            import asyncio
            import time

            from floatchat_api import health

            original_execute = psycopg.AsyncCursor.execute

            async def stalled_execute(cursor, query, *args, **kwargs):
                return await original_execute(
                    cursor,
                    "SELECT pg_sleep(5)" if query == "SELECT 1" else query,
                    *args,
                    **kwargs,
                )

            async def exercise():
                check = health.dependency_checks(settings)["database"]
                psycopg.AsyncCursor.execute = stalled_execute
                try:
                    start = time.monotonic()
                    assert not await health.ready({"database": check}, 0.1)
                    assert time.monotonic() - start <= 0.15
                finally:
                    psycopg.AsyncCursor.execute = original_execute
                await asyncio.sleep(0.15)
                assert not health._cleanup_tasks
                assert not check.connections and not check.deadlines

            asyncio.run(exercise())
            with psycopg.connect(settings.database_url.get_secret_value()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
                        "AND usename = current_user AND query LIKE '%%pg_sleep(5)%%'"
                    )
                    assert cursor.fetchone() == (0,)
        elif mode in ("queue", "worker"):
            # The work queue is PostgreSQL (migrations 0012/0013). Stage 0's application role
            # must see none of it: ticket claims, the metadata cache and level staging belong
            # to the ingestion login (scripts/bootstrap_db.py STAGE1_TABLES).
            with psycopg.connect(
                settings.database_url.get_secret_value(), autocommit=True
            ) as connection:
                with connection.cursor() as cursor:
                    for table in (
                        "processing_ticket",
                        "float_metadata_cache",
                        "measurement_staging",
                    ):
                        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"app.{table}",))
                        assert cursor.fetchone() == (True,)
                        cursor.execute(
                            "SELECT has_table_privilege(current_user, %s, "
                            "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                            (f"app.{table}",),
                        )
                        assert cursor.fetchone() == (False,)
                    cursor.execute(
                        "SELECT to_regprocedure('app.claim_ticket(text,text)') IS NOT NULL, "
                        "has_function_privilege(current_user, "
                        "'app.claim_ticket(text,text)', 'EXECUTE')"
                    )
                    assert cursor.fetchone() == (True, False)
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
