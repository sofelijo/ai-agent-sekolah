﻿import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

from .queries import create_dashboard_user
from .schema import ensure_dashboard_schema


def _handle_create_user(args: argparse.Namespace) -> None:
    password = args.password or getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password minimal 8 karakter.")
        sys.exit(1)

    password_hash = generate_password_hash(password, method="pbkdf2:sha256", salt_length=12)
    new_id = create_dashboard_user(
        email=args.email.lower(),
        full_name=args.full_name,
        password_hash=password_hash,
        role=args.role,
    )
    print(f"User berhasil dibuat dengan ID {new_id} dan role {args.role}.")


def _handle_init_db(_args: argparse.Namespace) -> None:
    ensure_dashboard_schema()
    print("Schema dashboard siap dipakai (dashboard_users dibuat bila belum ada).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard management CLI")
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser("create-user", help="Create dashboard user")
    create.add_argument("email", help="Email for login")
    create.add_argument("full_name", help="Display name")
    create.add_argument("--role", default="admin", choices=["admin", "editor", "viewer"], help="Role for the user")
    create.add_argument("--password", help="Plain password. If omitted, prompt securely.")

    init_db = subparsers.add_parser("init-db", help="Create dashboard tables if missing")

    args = parser.parse_args()

    if args.command == "create-user":
        _handle_create_user(args)
    elif args.command == "init-db":
        _handle_init_db(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
