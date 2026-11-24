"""Move existing dummy transactions off PJJ dates without changing monthly totals."""
import argparse
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import tempfile

from seed_library_history_2026 import END, START, TAG, calendar, service_day, validate


def consistent(rows):
    if any(r["return_date"] and r["return_date"] <= r["borrow_date"] for r in rows):
        return False
    for field in ("book_item_id", "student_id"):
        for value in {r[field] for r in rows}:
            ordered = sorted((r for r in rows if r[field] == value), key=lambda r: r["borrow_date"])
            if any(a["return_date"] is None or a["return_date"] > b["borrow_date"]
                   for a, b in zip(ordered, ordered[1:])):
                return False
    return True


def repair(original):
    rows = deepcopy(original)
    days = [d for d in calendar() if START <= d <= END]
    pending = [(row, field) for row in rows for field in ("borrow_date", "return_date")
               if row[field] is not None and not service_day(row[field])]

    def search(index):
        if index == len(pending):
            return True
        row, field = pending[index]
        old = row[field]
        # Same month preserves the exact approved monthly counts.
        choices = sorted((d for d in days if (d.year, d.month) == (old.year, old.month)),
                         key=lambda d: (abs((d - old).days), d < old))
        for candidate in choices:
            row[field] = candidate
            if consistent(rows) and search(index + 1):
                return True
        row[field] = old
        return False

    if not search(0):
        raise RuntimeError("No safe date assignment preserves monthly totals")
    for row in rows:
        if not service_day(row["due_date"]) or row["due_date"] <= row["borrow_date"]:
            candidate = max(row["due_date"], row["borrow_date"] + timedelta(days=1))
            while not service_day(candidate):
                candidate += timedelta(days=1)
            row["due_date"] = candidate
    validate(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extensions import adapt
    config = dotenv_values(args.project / ".env")
    demo = config["DASHBOARD_DEMO_DB_NAME"]
    if demo == config["DB_NAME"] or not demo.endswith("_dashboard_demo"):
        raise RuntimeError("Only the configured separate demo database may be repaired")

    def reader():
        return psycopg2.connect(dbname=demo, user=config["DASHBOARD_DEMO_DB_USER"],
            password=config["DASHBOARD_DEMO_DB_PASS"], host=config["DB_HOST"], port=config["DB_PORT"],
            connect_timeout=5, options="-c default_transaction_read_only=on")

    def fingerprint(cur, table):
        if table not in {"borrowing_records", "attendance_records"}:
            raise ValueError(table)
        cur.execute("SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'')) FROM public." + table + " t")
        return cur.fetchone()[0]

    conn = reader()
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == demo
        cur.execute("SELECT id,student_id,book_id,book_item_id,borrow_date,due_date,return_date,note FROM borrowing_records ORDER BY id")
        columns = [item[0] for item in cur.description]
        before = [dict(zip(columns, row)) for row in cur.fetchall()]
        assert len(before) == 115 and all(r["note"] == TAG for r in before)
        source_hash = fingerprint(cur, "borrowing_records")
        attendance_hash = fingerprint(cur, "attendance_records")
    conn.close()
    after = repair(before)
    changed = [(old, new) for old, new in zip(before, after) if old != new]
    print(json.dumps({"changed_records": len(changed), "changed_dates": {
        field: sum(old[field] != new[field] for old, new in changed)
        for field in ("borrow_date", "return_date", "due_date")},
        "total_loans": 115, "returned": 111, "outstanding": 4,
        "all_transaction_dates_valid": True}))
    if not args.apply or not changed:
        return
    backup = Path(tempfile.mkdtemp(prefix="aska-demo-library-before-pjj-", dir="/root"))
    with (backup / "borrowing_records.dump").open("wb") as output:
        subprocess.run(["sudo", "-u", "postgres", "pg_dump", "-Fc", "--no-owner", "--no-acl",
            "-d", demo, "-t", "public.borrowing_records"], cwd="/tmp", stdout=output, check=True)
    literal = lambda value: adapt(value).getquoted().decode()
    updates = []
    for old, new in changed:
        # Return timestamps precede same-day subsequent borrowing timestamps.
        created = new["borrow_date"].isoformat() + " 09:00:00+07"
        updated = (new["return_date"] or new["borrow_date"]).isoformat() + " 08:00:00+07"
        if new["return_date"] is None:
            updated = created
        updates.append("UPDATE public.borrowing_records SET borrow_date=%s,due_date=%s,return_date=%s,created_at=%s,updated_at=%s WHERE id=%s;" % tuple(literal(x) for x in (
            new["borrow_date"], new["due_date"], new["return_date"], created, updated, new["id"])))
    guard = """BEGIN;
    LOCK TABLE public.borrowing_records IN EXCLUSIVE MODE;
    DO $$ BEGIN
      IF current_database() <> %s OR
        (SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'')) FROM public.borrowing_records t) <> %s
      THEN RAISE EXCEPTION 'Database or rows changed; aborting'; END IF;
    END $$;
    """ % (literal(demo), literal(source_hash))
    subprocess.run(["sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", demo],
        cwd="/tmp", input=guard + "\n".join(updates) + "\nCOMMIT;", text=True, capture_output=True, check=True)
    conn = reader()
    with conn.cursor() as cur:
        cur.execute("SELECT id,student_id,book_id,book_item_id,borrow_date,due_date,return_date,note FROM borrowing_records ORDER BY id")
        committed = [dict(zip(columns, row)) for row in cur.fetchall()]
        assert committed == after
        validate(committed)
        assert fingerprint(cur, "attendance_records") == attendance_hash
        cur.execute("SELECT count(*) FILTER (WHERE status='returned'),count(*) FILTER (WHERE status='borrowed') FROM borrowing_records")
        assert cur.fetchone() == (111, 4)
    conn.close()
    print("PJJ cleanup verified; attendance unchanged. Private backup:", backup / "borrowing_records.dump")


if __name__ == "__main__":
    main()
