import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

from .queries import create_dashboard_user, get_user_by_email, upsert_dashboard_user
from .schema import ensure_dashboard_schema
from .attendance.importer import import_attendance_from_excel
from .attendance.teacher_importer import load_teacher_rows


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


def _handle_import_attendance(args: argparse.Namespace) -> None:
    ensure_dashboard_schema()
    import_attendance_from_excel(args.file, academic_year=args.academic_year)


def _handle_import_teachers(args: argparse.Namespace) -> None:
    ensure_dashboard_schema()
    teachers = load_teacher_rows(args.file)
    if not teachers:
        print("Tidak ada data guru yang ditemukan pada file tersebut.")
        return

    password = args.password or "tes"
    password_hash = generate_password_hash(password, method="pbkdf2:sha256", salt_length=12)

    inserted = 0
    updated = 0
    skipped = 0
    for teacher in teachers:
        email = (teacher.email or "").strip().lower()
        if not email:
            skipped += 1
            print(f"Melewati baris tanpa email: {teacher.full_name}")
            continue
        existing = get_user_by_email(email)
        upsert_dashboard_user(
            email=email,
            full_name=teacher.full_name,
            password_hash=password_hash,
            role="guru",
            nrk=teacher.nrk,
            nip=teacher.nip,
            jabatan=teacher.jabatan,
            degree_prefix=teacher.degree_prefix,
            degree_suffix=teacher.degree_suffix,
        )
        if existing:
            updated += 1
        else:
            inserted += 1

    print(f"Import guru selesai. Ditambahkan: {inserted}, diperbarui: {updated}, dilewati: {skipped}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard management CLI")
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser("create-user", help="Create dashboard user")
    create.add_argument("email", help="Email for login")
    create.add_argument("full_name", help="Display name")
    create.add_argument(
        "--role",
        default="admin",
        choices=["admin", "editor", "viewer", "guru"],
        help="Role for the user",
    )
    create.add_argument("--password", help="Plain password. If omitted, prompt securely.")

    init_db = subparsers.add_parser("init-db", help="Create dashboard tables if missing")

    import_cmd = subparsers.add_parser("import-attendance", help="Import student master data from Excel")
    import_cmd.add_argument("file", help="Path to Excel workbook")
    import_cmd.add_argument("--academic-year", help="Override academic year label (auto-detected when tersedia)")

    teacher_cmd = subparsers.add_parser("import-teachers", help="Import teacher users from Excel")
    teacher_cmd.add_argument("file", help="Path to Excel workbook")
    teacher_cmd.add_argument("--password", help='Password default untuk semua guru (default: "tes")', default="tes")

    args = parser.parse_args()

    if args.command == "create-user":
        _handle_create_user(args)
    elif args.command == "init-db":
        _handle_init_db(args)
    elif args.command == "import-attendance":
        _handle_import_attendance(args)
    elif args.command == "import-teachers":
        _handle_import_teachers(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
