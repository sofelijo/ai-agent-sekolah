"""Provision an isolated synthetic preview database on the production VPS.

Run as root with the project's venv Python. Only schema (no production rows) is
copied. Existing databases/roles are never overwritten. Re-running stops safely.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess

from dotenv import dotenv_values, set_key
import psycopg2
from psycopg2 import sql


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--resume-empty-demo", action="store_true")
    args = parser.parse_args()
    config_path = args.project / ".env"
    config_stat = config_path.stat()
    config = dotenv_values(config_path)
    original = config["DB_NAME"]
    demo = original[:40] + "_dashboard_demo"
    reader = "aska_dashboard_demo_reader"
    password = secrets.token_hex(32)
    if demo == original:
        raise RuntimeError("Demo database must be different from original")

    def postgres(statement, database="postgres"):
        result = subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", database],
            input=statement, text=True, capture_output=True,
        )
        if result.returncode:
            # Do not expose SQL containing a freshly generated password.
            raise RuntimeError("PostgreSQL provisioning failed; inspect server state before retrying.")

    conn = psycopg2.connect(
        dbname=original, user=config["DB_USER"], password=config["DB_PASS"],
        host=config["DB_HOST"], port=config["DB_PORT"], connect_timeout=5,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (demo,))
        demo_exists = bool(cur.fetchone())
        if demo_exists and not args.resume_empty_demo:
            raise RuntimeError("Demo database already exists; refusing to overwrite it")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (reader,))
        if cur.fetchone():
            raise RuntimeError("Demo reader already exists; refusing to overwrite it")
    env = dict(os.environ, PGPASSWORD=config["DB_PASS"])
    if config.get("DB_SSLMODE"):
        env["PGSSLMODE"] = config["DB_SSLMODE"]
    schema = subprocess.check_output([
        "pg_dump", "--schema-only", "--no-owner", "--no-acl",
        "-h", config["DB_HOST"], "-p", config["DB_PORT"],
        "-U", config["DB_USER"], "-d", original,
    ], env=env, text=True)
    if not demo_exists:
        postgres(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(demo)).as_string(conn))
        postgres(schema, demo)
    else:
        postgres("""DO $$ DECLARE r RECORD; has_rows BOOLEAN; BEGIN
        FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
          EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I LIMIT 1)', r.tablename) INTO has_rows;
          IF has_rows THEN RAISE EXCEPTION 'Refusing to seed a nonempty demo database'; END IF;
        END LOOP; END $$;""", demo)
    seed = (args.project / "deploy" / "seed_dashboard_demo.sql").read_text()
    postgres(seed, demo)
    # The reader can never write, even if a future route bypasses the UI guard.
    postgres(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; ALTER ROLE {} SET default_transaction_read_only=on;").format(
        sql.Identifier(reader), sql.Literal(password), sql.Identifier(reader),
    ).as_string(conn))
    postgres(sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(sql.Identifier(demo), sql.Identifier(reader)).as_string(conn))
    postgres(sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO {}; GRANT SELECT ON ALL TABLES IN SCHEMA public TO {};").format(
        sql.Identifier(reader), sql.Identifier(reader),
    ).as_string(conn), demo)
    allowed = {x.strip().lower() for x in config.get("DASHBOARD_DATA_MODE_ADMINS", "").split(",") if x.strip()}
    allowed.add(args.admin_email.strip().lower())
    for key, value in {
        "DASHBOARD_DEMO_DB_NAME": demo,
        "DASHBOARD_DEMO_DB_USER": reader,
        "DASHBOARD_DEMO_DB_PASS": password,
        "DASHBOARD_DATA_MODE_ADMINS": ",".join(sorted(allowed)),
    }.items():
        set_key(str(config_path), key, value)
    os.chown(config_path, config_stat.st_uid, config_stat.st_gid)
    os.chmod(config_path, config_stat.st_mode & 0o777)
    conn.close()
    print("Created isolated demo database with synthetic fixtures and read-only credentials.")


if __name__ == "__main__":
    main()
