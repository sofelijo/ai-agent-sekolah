"""Use real roster/catalog snapshots with synthetic transactions in demo only.

Original DB is read-only. SQL is streamed to a private file to keep memory low.
No passwords, family details, NIK/KK, or original transaction rows are copied.
Run with --apply as root on the VPS; dry-run only reports aggregate counts.
"""
import argparse
from collections import Counter
import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from academic_cohorts import academic_year_for, index_history, roster_on

from seed_attendance_history import school_dates
from seed_library_history_2026 import HOLIDAYS, CLOSURES, validate as validate_library

TAG = "DUMMY-TRANSACTIONS-ACADEMIC-YEARS-v2"
END = date(2026,11,23)
SPECS = {
    "school_classes": "id,name,academic_year,active",
    "dashboard_users": "id,email,full_name,role,assigned_class_id,degree_prefix,degree_suffix,jabatan",
    "students": "id,class_id,full_name,student_number,sequence,nisn,gender,active,student_status,status_academic_year,exit_date",
    "student_class_history": "id,student_id,academic_year,class_id,class_name,sequence,student_number,nisn,full_name,gender,graduation_date,graduation_status",
    "books": "id,title,author,publisher,year,code,stock,location",
    "book_items": "id,book_id,qr_code,status,is_labeled",
    "extracurriculars": "id,name,coach_name,coach_user_id,schedule_day,start_time,end_time,location,capacity,description,active,created_by,updated_by",
}
WEEKDAYS = {name:n for n,name in enumerate(["senin","selasa","rabu","kamis","jumat","sabtu","minggu"])}


def status_for(day, sid, salt="class"):
    number=int.from_bytes(hashlib.blake2b(f"{salt}|{day}|{sid}".encode(),digest_size=4).digest(),"big")%10000
    return "masuk" if number<9500 else "sakit" if number<9750 else "izin" if number<9950 else "alpa"


def grade(name):
    match=re.match(r"\s*([1-6])(?:\s|[A-Za-z]|$)",name)
    if not match:
        raise ValueError("Cannot infer elementary-school grade from class name")
    return int(match[1])


def activity_dates(activity):
    schedule=(activity["schedule_day"] or "").lower()
    weekdays={WEEKDAYS[value] for value in re.findall("|".join(WEEKDAYS),schedule)}
    if not activity["active"]:
        return []
    closed=CLOSURES+[(date(2026,3,28),date(2026,3,29))]
    return [date(2026,1,1)+timedelta(days=n) for n in range((END-date(2026,1,1)).days+1)
        if (date(2026,1,1)+timedelta(days=n)).weekday() in weekdays
        and date(2026,1,1)+timedelta(days=n) not in HOLIDAYS
        and not any(a<=date(2026,1,1)+timedelta(days=n)<=b for a,b in closed)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--project",type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extensions import adapt
    config=dotenv_values(args.project/".env")
    demo=config["DASHBOARD_DEMO_DB_NAME"]
    if demo==config["DB_NAME"] or not demo.endswith("_dashboard_demo"):
        raise RuntimeError("Refusing to modify anything except the separate demo DB")
    def connection(original=False):
        return psycopg2.connect(dbname=config["DB_NAME"] if original else demo,
            user=config["DB_USER"] if original else config["DASHBOARD_DEMO_DB_USER"],
            password=config["DB_PASS"] if original else config["DASHBOARD_DEMO_DB_PASS"],
            host=config["DB_HOST"],port=config["DB_PORT"],connect_timeout=8,
            options="-c default_transaction_read_only=on -c statement_timeout=30000")
    def dictionaries(cur,statement):
        cur.execute(statement)
        names=[r[0] for r in cur.description]
        return [dict(zip(names,row)) for row in cur.fetchall()]
    source=connection(True)
    source.set_session(isolation_level="REPEATABLE READ",readonly=True)
    snapshot={}
    with source.cursor() as cur:
        for table,columns in SPECS.items():
            snapshot[table]=dictionaries(cur,"SELECT "+columns+" FROM public."+table+" ORDER BY id")
        coaches=dictionaries(cur,"SELECT extracurricular_id,coach_user_id,assigned_by FROM extracurricular_coaches ORDER BY extracurricular_id,coach_user_id")
        original_members=dictionaries(cur,"SELECT extracurricular_id,student_id,role,joined_at,active FROM extracurricular_members ORDER BY extracurricular_id,student_id")
    source.rollback();source.close()
    classes={r["id"]:r for r in snapshot["school_classes"]}
    users={r["id"]:r for r in snapshot["dashboard_users"]}
    students={r["id"]:r for r in snapshot["students"]}
    active={sid:r for sid,r in students.items() if r["active"] and r["student_status"]=="aktif" and classes[r["class_id"]]["active"]}
    history_index=index_history(snapshot["student_class_history"])
    def dated_roster(day):
        return roster_on(history_index, students, day)
    allowed={x.strip().lower() for x in config["DASHBOARD_DATA_MODE_ADMINS"].split(",")}
    actor=next(uid for uid,u in users.items() if u["role"]=="admin" and u["email"].lower() in allowed)
    teacher_by_class={u["assigned_class_id"]:uid for uid,u in users.items() if u["role"]=="staff" and u["assigned_class_id"]}
    activities={r["id"]:r for r in snapshot["extracurriculars"]}
    activities[1]["name"]="Pramuka Siaga"
    members=[dict(r) for r in original_members if r["extracurricular_id"] not in (1,7)]
    scout_members={}
    for year,cohort in sorted(history_index.items()):
        for sid,h in cohort.items():
            aid=1 if grade(h["class_name"])<=3 else 7
            key=(aid,sid)
            current=history_index.get(academic_year_for(END),{}).get(sid)
            is_current=sid in active and current and (1 if grade(current["class_name"])<=3 else 7)==aid
            scout_members.setdefault(key,dict(extracurricular_id=aid,student_id=sid,role=None,
                joined_at=date(int(year[:4]),7,1),active=bool(is_current)))
    members.extend(scout_members.values())
    eligible={aid:[m for m in members if m["extracurricular_id"]==aid and m["active"] and m["student_id"] in active]
              for aid in activities}
    school_days=school_dates()
    school_set=set(school_days)
    calendar_by_activity={aid:activity_dates(a) for aid,a in activities.items()}
    def extracurricular_rows():
        for aid,a in activities.items():
            for day in calendar_by_activity[aid]:
                cohort=dated_roster(day)
                dated_members=([dict(student_id=sid,joined_at=None) for sid,h in cohort.items()
                    if (1 if grade(h["class_name"])<=3 else 7)==aid] if aid in (1,7) else
                    [m for m in members if m["extracurricular_id"]==aid and m["active"] and m["student_id"] in cohort])
                for member in dated_members:
                    if member["joined_at"] and day<member["joined_at"]:
                        continue
                    sid=member["student_id"]
                    school_status=status_for(day,sid) if day in school_set else "masuk"
                    status=school_status if school_status!="masuk" else status_for(day,sid,"ekskul")
                    timestamp=f"{day} {a['end_time'] or '14:00'}:00+07"
                    yield [day,aid,sid,status,TAG,"Latihan keterampilan dan kerja sama (dummy)",
                        a["coach_user_id"] or actor,timestamp,timestamp]
    summary={"active_students":len(active),"all_students":len(students),"classes":len(classes),
        "siaga":len(eligible[1]),"penggalang":len(eligible[7]),"books":len(snapshot["books"]),
        "copies":len(snapshot["book_items"]),"daily_records":sum(len(dated_roster(day)) for day in school_days),
        "year_rosters":{year:len(cohort) for year,cohort in history_index.items()},
        "activities":[{"name":a["name"],"active_members":len(eligible[aid]),"scheduled_days":len(calendar_by_activity[aid])}
                      for aid,a in activities.items()],
        "extracurricular_records":sum(1 for _ in extracurricular_rows())}
    print(json.dumps(summary,ensure_ascii=False))
    if not args.apply:
        return
    current=connection()
    with current.cursor() as cur:
        library=dictionaries(cur,"SELECT id,student_id,book_id,book_item_id,borrow_date,due_date,return_date,status FROM borrowing_records ORDER BY id")
        validate_library(library)
    current.close()
    rng=random.Random(20261123)
    used=set()
    for row in library:
        allowed_borrowers=set(dated_roster(row["borrow_date"])) & set(dated_roster(row["return_date"] or END))
        options=sorted(allowed_borrowers-used)
        if not options:
            raise RuntimeError("No enrolled student covers both loan and return dates")
        sid=row["student_id"] if row["student_id"] in options else rng.choice(options)
        used.add(sid)
        row["student_id"]=sid
    validate_library(library)
    backup=Path(tempfile.mkdtemp(prefix="aska-demo-before-real-masters-",dir="/root"))
    with (backup/"demo.dump").open("wb") as output:
        subprocess.run(["sudo","-u","postgres","pg_dump","-Fc","--no-owner","--no-acl","-d",demo],cwd="/tmp",stdout=output,check=True)
    literal=lambda value:adapt(value).getquoted().decode()
    sql_path=backup/"migration.sql"
    with sql_path.open("w",newline="") as out:
        sql_path.chmod(0o600)
        def sql(statement):out.write(statement+"\n")
        def copy(table,columns,rows):
            sql("COPY "+table+" ("+",".join(columns)+") FROM STDIN WITH (FORMAT CSV,NULL '\\N');")
            writer=csv.writer(out,lineterminator="\n")
            count=0
            for row in rows:
                writer.writerow(["\\N" if v is None else v for v in row]);count+=1
            sql("\\.")
            return count
        sql("BEGIN; SET LOCAL statement_timeout='180s'; SET LOCAL lock_timeout='20s';")
        sql("DO $$ BEGIN IF current_database() <> "+literal(demo)+" THEN RAISE EXCEPTION 'Wrong DB'; END IF; END $$;")
        sql("LOCK TABLE "+",".join("public."+t for t in SPECS)+",public.attendance_records,public.borrowing_records,public.extracurricular_attendance_records,public.extracurricular_members,public.extracurricular_coaches IN EXCLUSIVE MODE;")
        for table in ("attendance_records","borrowing_records","extracurricular_attendance_records","extracurricular_members","extracurricular_coaches","student_class_history"):
            sql("DELETE FROM public."+table+";")
        for table,column_string in SPECS.items():
            columns=column_string.split(",")
            rows=snapshot[table]
            if table=="dashboard_users":
                columns=columns+["password_hash"]
                rows=[{**r,"password_hash":"!demo-login-disabled"} for r in rows]
            if table=="book_items":
                rows=[{**r,"status":"available" if r["status"]=="borrowed" else r["status"]} for r in rows]
            stage="real_master_"+table
            sql("CREATE TEMP TABLE "+stage+" (LIKE public."+table+" INCLUDING DEFAULTS) ON COMMIT DROP;")
            copy(stage,columns,([r.get(c) for c in columns] for r in rows))
            updates=",".join(c+"=EXCLUDED."+c for c in columns if c!="id")
            sql("INSERT INTO public."+table+" ("+",".join(columns)+") SELECT "+",".join(columns)+" FROM "+stage+" ON CONFLICT (id) DO UPDATE SET "+updates+";")
        # Re-key the existing point example before discarding placeholder students.
        sql("UPDATE student_point_records SET student_id="+str(min(active))+",recorded_by="+str(actor)+";")
        for table in ("students","book_items","books"):
            sql("DELETE FROM public."+table+" WHERE id NOT IN (SELECT id FROM real_master_"+table+");")
        copy("public.extracurricular_coaches",["extracurricular_id","coach_user_id","assigned_by"],
            ([r[c] for c in ("extracurricular_id","coach_user_id","assigned_by")] for r in coaches))
        copy("public.extracurricular_members",["extracurricular_id","student_id","role","joined_at","active"],
            ([r[c] for c in ("extracurricular_id","student_id","role","joined_at","active")] for r in members))
        def daily_rows():
            for day in school_days:
                for sid,h in dated_roster(day).items():
                    timestamp=f"{day} 07:15:00+07"
                    yield [day,sid,h["class_id"],teacher_by_class.get(h["class_id"],actor),status_for(day,sid),TAG,timestamp,timestamp]
        count=copy("public.attendance_records",["attendance_date","student_id","class_id","teacher_id","status","note","recorded_at","updated_at"],daily_rows())
        assert count==summary["daily_records"]
        count=copy("public.extracurricular_attendance_records",["attendance_date","extracurricular_id","student_id","status","note","material","recorded_by","recorded_at","updated_at"],extracurricular_rows())
        assert count==summary["extracurricular_records"]
        copy("public.borrowing_records",["id","student_id","book_id","book_item_id","borrow_date","due_date","return_date","status","note","recorded_by","returned_by","created_at","updated_at"],
            ([r["id"],r["student_id"],r["book_id"],r["book_item_id"],r["borrow_date"],r["due_date"],r["return_date"],r["status"],TAG,actor,
              actor if r["return_date"] else None,f"{r['borrow_date']} 09:00:00+07",f"{r['return_date'] or r['borrow_date']} 13:00:00+07"] for r in library))
        sql("UPDATE book_items SET status='borrowed' WHERE id IN (SELECT book_item_id FROM borrowing_records WHERE status='borrowed');")
        sql("UPDATE books b SET stock=(SELECT count(*) FROM book_items i WHERE i.book_id=b.id AND i.status='available');")
        for table in (*SPECS,"extracurricular_members","attendance_records","extracurricular_attendance_records","borrowing_records"):
            sql("SELECT setval(pg_get_serial_sequence('public.%s','id'),greatest(coalesce((SELECT max(id) FROM public.%s),0),1));"%(table,table))
        sql("DO $$ BEGIN IF (SELECT count(*) FROM attendance_records)<>%d OR (SELECT count(*) FROM extracurricular_attendance_records)<>%d OR (SELECT count(*) FROM borrowing_records)<>115 THEN RAISE EXCEPTION 'Wrong totals'; END IF; END $$;"%(summary["daily_records"],summary["extracurricular_records"]))
        sql("COMMIT;")
    with sql_path.open() as input_file:
        result=subprocess.run(["sudo","-u","postgres","psql","-X","-v","ON_ERROR_STOP=1","-d",demo],cwd="/tmp",stdin=input_file,text=True,capture_output=True)
    if result.returncode:
        (backup/"failure.log").write_text(result.stderr)
        raise RuntimeError("Migration rolled back; private error log: "+str(backup/"failure.log"))
    sql_path.unlink()
    current=connection()
    with current.cursor() as cur:
        for table,columns in SPECS.items():
            if table=="books":columns=",".join(c for c in columns.split(",") if c!="stock")
            if table=="book_items":columns=",".join(c for c in columns.split(",") if c!="status")
            actual=dictionaries(cur,"SELECT "+columns+" FROM "+table+" ORDER BY id")
            expected=[{c:r[c] for c in columns.split(",")} for r in snapshot[table]]
            assert actual==expected,table
        cur.execute("SELECT count(*),count(DISTINCT student_id),count(DISTINCT attendance_date),min(attendance_date),max(attendance_date) FROM attendance_records")
        expected_students=set().union(*(set(dated_roster(day)) for day in school_days))
        assert cur.fetchone()==(summary["daily_records"],len(expected_students),220,school_days[0],END)
        cur.execute("SELECT attendance_date,class_id,count(*) FROM attendance_records GROUP BY attendance_date,class_id")
        actual_daily={(day,cid):count for day,cid,count in cur.fetchall()}
        expected_daily={}
        for day in school_days:
            for cid,count in Counter(h["class_id"] for h in dated_roster(day).values()).items():
                expected_daily[(day,cid)]=count
        assert actual_daily==expected_daily
        cur.execute("SELECT count(*) FILTER(WHERE extracurricular_id=1),count(*) FILTER(WHERE extracurricular_id=7) FROM extracurricular_members WHERE active")
        assert cur.fetchone()==(summary["siaga"],summary["penggalang"])
        cur.execute("SELECT count(*) FROM extracurricular_attendance_records a LEFT JOIN extracurricular_members m ON m.extracurricular_id=a.extracurricular_id AND m.student_id=a.student_id WHERE m.id IS NULL")
        assert cur.fetchone()[0]==0
        actual=dictionaries(cur,"SELECT student_id,book_id,book_item_id,borrow_date,due_date,return_date FROM borrowing_records")
        validate_library(actual)
        for row in actual:
            assert row["student_id"] in dated_roster(row["borrow_date"])
            assert row["student_id"] in dated_roster(row["return_date"] or END)
        cur.execute("SELECT DISTINCT attendance_date,extracurricular_id,student_id FROM extracurricular_attendance_records")
        for day,aid,sid in cur.fetchall():
            cohort=dated_roster(day)
            assert sid in cohort
            if aid in (1,7):assert aid==(1 if grade(cohort[sid]["class_name"])<=3 else 7)
        cur.execute("SELECT count(*) FILTER(WHERE status='returned'),count(*) FILTER(WHERE status='borrowed') FROM borrowing_records")
        assert cur.fetchone()==(111,4)
    current.close()
    print("Real master snapshots and synthetic transactions verified. Private backup:",backup/"demo.dump")


if __name__=="__main__":
    main()
