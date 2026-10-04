"""Migration and local role initialization; never erase existing data."""

import os
import subprocess
import sys

import psycopg
from psycopg import sql


def main() -> None:
    subprocess.run(
        ["alembic", "-c", "infra/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("floatchat_app",))
            if cursor.fetchone() is None:
                cursor.execute(
                    "CREATE ROLE floatchat_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
                )
            cursor.execute(
                sql.SQL("ALTER ROLE floatchat_app PASSWORD {}").format(
                    sql.Literal(os.environ["DB_APP_PASSWORD"])
                )
            )
            cursor.execute("GRANT CONNECT ON DATABASE floatchat TO floatchat_app")
            cursor.execute("GRANT USAGE ON SCHEMA public TO floatchat_app")
            cursor.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                "TO floatchat_app"
            )
            cursor.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO floatchat_app")
            cursor.execute("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM floatchat_app")
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, "
                "UPDATE, DELETE ON TABLES TO floatchat_app"
            )
            cursor.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES "
                "TO floatchat_app"
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
