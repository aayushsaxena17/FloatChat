"""Migration and local role initialization; never erase existing data."""

import os
import subprocess
import sys

import psycopg
from psycopg import sql

STAGE1_TABLES = frozenset(
    {
        "ingestion_environment",
        "ingestion_run",
        "ingestion_chunk",
        "ingestion_attempt",
        "raw_manifest",
        "argo_float",
        "argo_profile",
        "core_measurement",
        "logical_partition_slot",
        "publication_intent",
        "dataset_partition",
        "coverage_receipt",
        "ingestion_event",
        "profile_outcome",
        "ingestion_scope",
        "scheduling_attempt",
        "ingestion_staging",
        "ingestion_input",
        "canonical_work",
        "run_baseline",
        "run_final_evidence",
        "chunk_accounting",
        "processing_ticket",
        "landing_reset",
        "ingestion_event_sequence_seq",
        "profile_outcome_sequence_seq",
    }
)


def ensure_application_role(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("floatchat_app",))
    if cursor.fetchone() is None:
        cursor.execute("CREATE ROLE floatchat_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")


def main() -> None:
    # Stage 1 migrations revoke privileges from floatchat_app, so a fresh database
    # needs the role before migrating, not only afterwards.
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            ensure_application_role(cursor)
    subprocess.run(
        ["alembic", "-c", "infra/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            ensure_application_role(cursor)
            cursor.execute(
                sql.SQL("ALTER ROLE floatchat_app PASSWORD {}").format(
                    sql.Literal(os.environ["DB_APP_PASSWORD"])
                )
            )
            cursor.execute("GRANT CONNECT ON DATABASE floatchat TO floatchat_app")
            cursor.execute("GRANT USAGE ON SCHEMA public TO floatchat_app")
            cursor.execute("CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION floatchat_admin")
            cursor.execute("GRANT USAGE ON SCHEMA app TO floatchat_app")
            cursor.execute("SELECT to_regclass('app.committed_active_partitions')")
            if cursor.fetchone()[0] is not None:
                cursor.execute("GRANT SELECT ON app.committed_active_partitions TO floatchat_app")
            # Remove the previous public-schema defaults and blanket write grants.
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, "
                "DELETE ON TABLES FROM floatchat_app"
            )
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE ON SEQUENCES "
                "FROM floatchat_app"
            )
            cursor.execute(
                "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                "ON ALL TABLES IN SCHEMA public FROM floatchat_app"
            )
            cursor.execute("REVOKE ALL ON alembic_version FROM floatchat_app")
            # Extension members can occur in schemas other than public too.
            cursor.execute(
                "SELECT n.nspname, c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_depend d ON d.classid = 'pg_class'::regclass AND d.objid = c.oid "
                "WHERE d.refclassid = 'pg_extension'::regclass AND d.deptype = 'e' "
                "AND c.relkind IN ('r','p','v','m','f')"
            )
            for schema, table in cursor.fetchall():
                cursor.execute(
                    sql.SQL(
                        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                        "ON TABLE {}.{} FROM floatchat_app"
                    ).format(sql.Identifier(schema), sql.Identifier(table))
                )
                cursor.execute(
                    sql.SQL("GRANT SELECT ON TABLE {}.{} TO floatchat_app").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
            # Application objects are owned by the migration role in the app schema.
            # Never include extension members in existing-object grants.
            cursor.execute(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'app' AND c.relowner = current_user::regrole "
                "AND c.relkind IN ('r','p','S') AND NOT EXISTS "
                "(SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass "
                "AND d.objid = c.oid AND d.refclassid = 'pg_extension'::regclass "
                "AND d.deptype = 'e')"
            )
            for name, kind in cursor.fetchall():
                if name in STAGE1_TABLES or name.startswith("core_measurement_"):
                    cursor.execute(
                        sql.SQL("REVOKE ALL ON {} app.{} FROM floatchat_app").format(
                            sql.SQL("SEQUENCE" if kind == "S" else "TABLE"), sql.Identifier(name)
                        )
                    )
                    continue
                privileges = "USAGE" if kind == "S" else "SELECT, INSERT, UPDATE, DELETE"
                object_type = "SEQUENCE" if kind == "S" else "TABLE"
                cursor.execute(
                    sql.SQL("GRANT {} ON {} app.{} TO floatchat_app").format(
                        sql.SQL(privileges), sql.SQL(object_type), sql.Identifier(name)
                    )
                )
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE SELECT, INSERT, UPDATE, "
                "DELETE ON TABLES FROM floatchat_app"
            )
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE USAGE "
                "ON SEQUENCES FROM floatchat_app"
            )
            cursor.execute("SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector')")
            if {row[0] for row in cursor.fetchall()} != {"postgis", "vector"}:
                raise RuntimeError("required extensions unavailable")


if __name__ == "__main__":
    try:
        main()
        print("Database initialization complete.")
    except Exception:
        print("Database initialization failed; no sensitive diagnostics emitted.", file=sys.stderr)
        raise SystemExit(1) from None
