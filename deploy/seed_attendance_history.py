"""Synthetic student attendance, physical school days only. Dry-run by default."""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import random
import subprocess
import tempfile

from seed_library_history_2026 import HOLIDAYS, CLOSURES

START = date(2025, 11, 5)
END = date(2026, 11, 23)  # Approved cutoff, Asia/Jakarta.
TAG = "DUMMY-ATTENDANCE-20251105-20261123"
EXCLUDED_DATES = HOLIDAYS | {date(2025, 12, 25), date(2025, 12, 26)}
# DKI school calendar: https://edu.jakarta.go.id/cdn/files/photos/cms/kalender20252026.pdf
# PJJ Jan: https://m.beritajakarta.id/read/150482/pramono-perpanjang-masa-pjj-sampai-1-februari
# PJJ Sep: https://m.beritajakarta.id/read/155279/pemprov-dki-perpanjang-pjj-sampai-8-september
EXCLUDED_RANGES = CLOSURES + [
    (date(2025, 12, 20), date(2026, 1, 3)),
]
STUDENTS = {student: 1 + (student - 1) % 3 + (3 if student > 9 else 0)
            for student in range(1, 19)}


def school_day(day):
    return (day.weekday() < 5 and day not in EXCLUDED_DATES
            and not any(first <= day <= last for first, last in EXCLUDED_RANGES))


def school_dates():
    return [START + timedelta(days=n) for n in range((END - START).days + 1)
            if school_day(START + timedelta(days=n))]


def generate_entries():
    rng = random.Random(2025110520261123)
    entries = []
    for day in school_dates():
        for student, class_id in STUDENTS.items():
            status = rng.choices(["masuk", "sakit", "izin", "alpa"], [95, 2.5, 2, 0.5])[0]
            entries.append(dict(attendance_date=day, student_id=student, class_id=class_id,
                                teacher_id=28, status=status, note=TAG + " / " + status))
    validate(entries)
    return entries


def validate(entries):
    days = school_dates()
    assert len(days) == 220 and days[0] == START and days[-1] == END
    expected = {(day, student) for day in days for student in STUDENTS}
    assert len(entries) == len(expected) == 3960
    assert {(r["attendance_date"], r["student_id"]) for r in entries} == expected
    for row in entries:
        assert row["class_id"] == STUDENTS[row["student_id"]]
        assert row["teacher_id"] == 28
        assert row["status"] in {"masuk", "sakit", "izin", "alpa"}
        assert row["note"].startswith(TAG)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    rows = generate_entries()
    print(json.dumps({"first_date": str(START), "last_date": str(END),
        "school_days": len(school_dates()), "students": len(STUDENTS), "records": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "days_per_month": dict(Counter(d.strftime("%Y-%m") for d in school_dates()))}))
    if not args.apply:
        return
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extensions import adapt
    config = dotenv_values(args.project / ".env")
    demo = config["DASHBOARD_DEMO_DB_NAME"]
    if demo == config["DB_NAME"] or not demo.endswith("_dashboard_demo"):
        raise RuntimeError("Refusing to write outside the configured demo database")

    def reader():
        return psycopg2.connect(dbname=demo, user=config["DASHBOARD_DEMO_DB_USER"],
            password=config["DASHBOARD_DEMO_DB_PASS"], host=config["DB_HOST"], port=config["DB_PORT"],
            connect_timeout=5, options="-c default_transaction_read_only=on")

    conn = reader()
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == demo
        cur.execute("SELECT id,class_id FROM students WHERE active AND full_name LIKE 'Siswa Demo %' ORDER BY id")
        assert dict(cur.fetchall()) == STUDENTS
        cur.execute("SELECT role FROM dashboard_users WHERE id=28")
        assert cur.fetchone()[0] == "staff"
        cur.execute("SELECT count(*),count(*) FILTER (WHERE note LIKE %s) FROM attendance_records", (TAG + "%",))
        count, tagged = cur.fetchone()
        if not (count == 126 or count == tagged == len(rows)):
            raise RuntimeError("Unexpected demo attendance; refusing replacement")
        cur.execute("SELECT count(*), count(*) FILTER (WHERE status='returned') FROM borrowing_records")
        library_before = cur.fetchone()
    conn.close()
    backup = Path(tempfile.mkdtemp(prefix="aska-demo-attendance-before-history-", dir="/root"))
    with (backup / "attendance.dump").open("wb") as output:
        subprocess.run(["sudo", "-u", "postgres", "pg_dump", "-Fc", "--no-owner", "--no-acl",
            "-d", demo, "-t", "public.attendance_records"], cwd="/tmp", stdout=output, check=True)
    literal = lambda value: adapt(value).getquoted().decode()
    values = []
    for row in rows:
        timestamp = row["attendance_date"].isoformat() + " 07:15:00+07"
        values.append("(" + ",".join(literal(value) for value in (
            row["attendance_date"], row["student_id"], row["class_id"], row["teacher_id"],
            row["status"], row["note"], timestamp, timestamp,
        )) + ")")
    statement = """BEGIN;
    DO $$ BEGIN IF current_database() <> %s THEN RAISE EXCEPTION 'Wrong database'; END IF; END $$;
    LOCK TABLE public.attendance_records IN EXCLUSIVE MODE;
    DELETE FROM public.attendance_records;
    INSERT INTO public.attendance_records
      (attendance_date,student_id,class_id,teacher_id,status,note,recorded_at,updated_at)
      VALUES %s;
    DO $$ BEGIN
      IF (SELECT count(*) FROM public.attendance_records) <> 3960 OR
         (SELECT count(DISTINCT attendance_date) FROM public.attendance_records) <> 220 OR
         EXISTS (SELECT 1 FROM public.attendance_records WHERE extract(isodow FROM attendance_date)>5)
      THEN RAISE EXCEPTION 'Invalid attendance fixtures'; END IF;
    END $$;
    COMMIT;""" % (literal(demo), ",\n".join(values))
    subprocess.run(["sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", demo],
        cwd="/tmp", input=statement, text=True, check=True, capture_output=True)
    conn = reader()
    with conn.cursor() as cur:
        cur.execute("SELECT attendance_date,student_id,class_id,teacher_id,status,note FROM attendance_records")
        columns = [item[0] for item in cur.description]
        validate([dict(zip(columns, row)) for row in cur.fetchall()])
        cur.execute("SELECT count(*),count(*) FILTER (WHERE status='returned') FROM borrowing_records")
        assert cur.fetchone() == library_before
    conn.close()
    print("Applied and verified dummy attendance; library unchanged. Private backup:", backup / "attendance.dump")


if __name__ == "__main__":
    main()
