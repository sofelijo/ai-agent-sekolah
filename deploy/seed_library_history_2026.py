"""Reproducible, approved library fixtures. Dry-run by default; demo DB only."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import random
import subprocess

START = date(2026, 1, 1)
END = date(2026, 11, 23)
TARGET_LOANS = [10, 10, 6, 13, 8, 10, 10, 12, 11, 14, 11]
TARGET_RETURNS = [9, 8, 8, 12, 9, 11, 8, 11, 12, 13, 10]
TARGET_DAYS = [13, 15, 12, 21, 16, 18, 15, 19, 20, 22, 16]
TAG = "DUMMY-LIBRARY-2026-v1"
# SKB 2026: https://www.kemenkopmk.go.id/pemerintah-tetapkan-17-hari-libur-nasional-dan-8-hari-cuti-bersama-tahun-2026
HOLIDAYS = {date.fromisoformat("2026-" + value) for value in (
    "01-01", "01-16", "02-16", "02-17", "03-18", "03-19", "03-20",
    "03-21", "03-22", "03-23", "03-24", "04-03", "04-05", "05-01",
    "05-14", "05-15", "05-27", "05-28", "05-31", "06-01", "06-16",
    "08-17", "08-25", "12-24", "12-25",
)}
# DKI school calendar and the final SEB Ramadan 2026: exclude home-learning days too.
# https://m.beritajakarta.id/read/150482/pramono-perpanjang-masa-pjj-sampai-1-februari
# https://m.beritajakarta.id/read/155279/pemprov-dki-perpanjang-pjj-sampai-8-september
PJJ_CLOSURES = [
    (date(2026, 1, 23), date(2026, 2, 1)),
    (date(2026, 9, 7), date(2026, 9, 8)),
]
CLOSURES = PJJ_CLOSURES + [
    (date(2026, 1, 1), date(2026, 1, 3)),
    (date(2026, 2, 18), date(2026, 2, 21)),
    (date(2026, 3, 16), date(2026, 3, 27)),
    (date(2026, 6, 27), date(2026, 7, 11)),
]


def service_day(day):
    return day.weekday() < 5 and day not in HOLIDAYS and not any(a <= day <= b for a, b in CLOSURES)


def calendar():
    return [START + timedelta(days=n) for n in range((date(2026, 12, 18) - START).days + 1)
            if service_day(START + timedelta(days=n))]


def build_history():
    rng = random.Random(20261123)
    days = calendar()
    history = []
    carry = []
    for month, (loans, returns) in enumerate(zip(TARGET_LOANS, TARGET_RETURNS), 1):
        month_days = [d for d in days if d.month == month and d <= END]
        assert len(month_days) == TARGET_DAYS[month - 1]
        for index, previous in enumerate(carry):
            previous["return_date"] = month_days[index % min(3, len(month_days))]
        same_month_returns = returns - len(carry)
        carry = []
        # Spread most loans across the month, leaving capacity for carry-over loans.
        for index in range(same_month_returns):
            begin = round(index * (len(month_days) - 8) / max(1, same_month_returns - 1))
            begin = max(0, begin + rng.choice([0, 0, 1]))
            finish = min(begin + rng.randint(2, 7), len(month_days) - 1)
            history.append({"borrow_date": month_days[begin], "return_date": month_days[finish]})
        for index in range(loans - same_month_returns):
            row = {"borrow_date": month_days[-3 + index % 3], "return_date": None}
            history.append(row)
            carry.append(row)
    # Assign each physical copy/student only when their preceding loan has returned.
    copy_end = {n: START for n in range(1, 10)}
    student_end = {n: START for n in range(1, 19)}
    for row in sorted(history, key=lambda r: (r["borrow_date"], r["return_date"] or date.max)):
        day = row["borrow_date"]
        copies = [n for n, until in copy_end.items() if until <= day]
        students = [n for n, until in student_end.items() if until <= day]
        assert copies and students, "Insufficient inventory for fixture schedule"
        copy = rng.choice(copies)
        student = rng.choice(students)
        row.update(book_item_id=copy, book_id=1 + (copy - 1) // 3, student_id=student,
                   due_date=days[days.index(day) + 5])
        copy_end[copy] = row["return_date"] or date.max
        student_end[student] = row["return_date"] or date.max
    validate(history)
    return sorted(history, key=lambda r: (r["borrow_date"], r["book_item_id"]))


def validate(rows):
    assert len(rows) == 115
    assert sum(r["return_date"] is not None for r in rows) == 111
    for month in range(1, 12):
        assert sum(r["borrow_date"].month == month for r in rows) == TARGET_LOANS[month - 1]
        assert sum(r["return_date"] is not None and r["return_date"].month == month for r in rows) == TARGET_RETURNS[month - 1]
    for row in rows:
        assert START <= row["borrow_date"] <= END and service_day(row["borrow_date"])
        assert service_day(row["due_date"]) and row["due_date"] > row["borrow_date"]
        if row["return_date"]:
            assert row["borrow_date"] < row["return_date"] <= END and service_day(row["return_date"])
    for key in ("book_item_id", "student_id"):
        for value in {r[key] for r in rows}:
            matches = sorted((r for r in rows if r[key] == value), key=lambda r: r["borrow_date"])
            assert all(a["return_date"] and a["return_date"] <= b["borrow_date"] for a, b in zip(matches, matches[1:]))


def apply(project, rows):
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extensions import adapt
    config = dotenv_values(project / ".env")
    demo = config["DASHBOARD_DEMO_DB_NAME"]
    assert demo != config["DB_NAME"] and demo.endswith("_dashboard_demo")
    conn = psycopg2.connect(dbname=demo, user=config["DASHBOARD_DEMO_DB_USER"],
        password=config["DASHBOARD_DEMO_DB_PASS"], host=config["DB_HOST"], port=config["DB_PORT"],
        connect_timeout=5, options="-c default_transaction_read_only=on")
    with conn.cursor() as q:
        q.execute("SELECT current_database()")
        assert q.fetchone()[0] == demo
        q.execute("SELECT id,book_id FROM book_items WHERE qr_code LIKE 'DEMO-ITEM-%' ORDER BY id")
        assert q.fetchall() == [(n, 1 + (n - 1) // 3) for n in range(1, 10)]
        q.execute("SELECT id FROM students WHERE full_name LIKE 'Siswa Demo %' ORDER BY id")
        assert [r[0] for r in q.fetchall()] == list(range(1, 19))
        q.execute("SELECT count(*),count(*) FILTER (WHERE note=%s) FROM borrowing_records", (TAG,))
        count, tagged = q.fetchone()
        assert count == 3 or count == tagged == 115, "Unexpected existing history; refusing replacement"
    conn.close()
    # Reversible replacement: preserve all affected tables before the transaction.
    backup = Path("/root/aska-demo-library-before-history-20261123")
    backup.mkdir(mode=0o700, exist_ok=False)
    with (backup / "library.dump").open("wb") as output:
        subprocess.run(["sudo", "-u", "postgres", "pg_dump", "-Fc", "--no-owner", "--no-acl",
            "-d", demo, "-t", "public.books", "-t", "public.book_items", "-t", "public.borrowing_records"],
            cwd="/tmp", stdout=output, check=True)
    def literal(value):
        return adapt(value).getquoted().decode()
    values = []
    for row in rows:
        returned = row["return_date"]
        created = row["borrow_date"].isoformat() + " 09:00:00+07"
        updated = (returned or row["borrow_date"]).isoformat() + " 13:00:00+07"
        values.append("(" + ",".join(literal(x) for x in (
            row["student_id"], row["book_id"], row["book_item_id"], row["borrow_date"],
            row["due_date"], returned, "returned" if returned else "borrowed", TAG, 27,
            28 if returned else None, created, updated,
        )) + ")")
    statement = """BEGIN;
    DO $$ BEGIN IF current_database() <> %s THEN RAISE EXCEPTION 'Wrong database'; END IF; END $$;
    LOCK TABLE public.borrowing_records, public.book_items IN EXCLUSIVE MODE;
    DELETE FROM public.borrowing_records;
    INSERT INTO public.borrowing_records
      (student_id,book_id,book_item_id,borrow_date,due_date,return_date,status,note,recorded_by,returned_by,created_at,updated_at)
      VALUES %s;
    UPDATE public.book_items SET status=CASE WHEN EXISTS (
      SELECT 1 FROM public.borrowing_records r WHERE r.book_item_id=book_items.id AND r.status='borrowed'
    ) THEN 'borrowed' ELSE 'available' END, updated_at=NOW();
    DO $$ BEGIN
      IF (SELECT count(*) FROM public.borrowing_records) <> 115 OR
         (SELECT count(*) FROM public.borrowing_records WHERE status='returned') <> 111 OR
         (SELECT count(*) FROM public.book_items WHERE status='borrowed') <> 4
      THEN RAISE EXCEPTION 'Fixture totals do not match'; END IF;
    END $$;
    COMMIT;""" % (literal(demo), ",\n".join(values))
    subprocess.run(["sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", demo],
                   cwd="/tmp", input=statement, text=True, check=True, capture_output=True)
    # Re-read committed database rows with the dashboard's read-only credentials.
    conn = psycopg2.connect(dbname=demo, user=config["DASHBOARD_DEMO_DB_USER"],
        password=config["DASHBOARD_DEMO_DB_PASS"], host=config["DB_HOST"], port=config["DB_PORT"])
    with conn.cursor() as q:
        q.execute("SELECT student_id,book_id,book_item_id,borrow_date,due_date,return_date FROM borrowing_records")
        names = [column[0] for column in q.description]
        validate([dict(zip(names, row)) for row in q.fetchall()])
    conn.close()
    print("Inserted and verified demo history; private backup:", backup / "library.dump")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    history = build_history()
    print(json.dumps({"service_days": TARGET_DAYS, "loans": TARGET_LOANS,
        "returns": TARGET_RETURNS, "total_loans": len(history), "total_returns": 111,
        "outstanding": 4, "applied": args.apply}))
    if args.apply:
        apply(args.project, history)
