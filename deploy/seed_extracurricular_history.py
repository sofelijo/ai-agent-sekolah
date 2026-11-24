"""Seed synthetic extracurriculars, grade-appropriate members and 2026 attendance.

Uses regular stored schedules, including Saturday for futsal/pencak silat.
Only the explicitly separate demo DB can be changed. Dry-run by default.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import random
import subprocess
import tempfile

from seed_library_history_2026 import HOLIDAYS, CLOSURES
from seed_attendance_history import STUDENTS, generate_entries

START, END = date(2026, 1, 1), date(2026, 11, 23)
TAG = "DUMMY-EKSKUL-20260101-20261123"
CLASSES = {1: "1A Demo", 2: "2A Demo", 3: "6A Demo", 4: "3A Demo", 5: "4A Demo", 6: "5A Demo"}
GRADE = {key: int(name[0]) for key, name in CLASSES.items()}
SIAGA = [sid for sid, cid in STUDENTS.items() if GRADE[cid] <= 3]
PENGGALANG = [sid for sid, cid in STUDENTS.items() if GRADE[cid] >= 4]
# IDs follow the original extracurricular master, but only synthetic members are used.
ACTIVITIES = {
    1: dict(name="Pramuka Siaga", days=[2], schedule="Rabu", start="11:00", end="12:00", members=SIAGA),
    2: dict(name="Pencak Silat", days=[5], schedule="Sabtu", start="10:00", end="12:00", members=[4,5,6,7,8,9,13,14]),
    3: dict(name="Tari Tradisional", days=[2], schedule="Rabu", start="10:00", end="11:00", members=[1,2,4,5,7,8,10,11,13,14,16,17]),
    4: dict(name="Futsal", days=[5], schedule="Sabtu", start="08:00", end="10:00", members=[1,2,3,4,5,6,10,11,12,15]),
    5: dict(name="Marawis", days=[1,3], schedule="Selasa, Kamis", start="10:00", end="11:30", members=[3,6,9,10,11,12,13,14,15,18]),
    6: dict(name="PMR", days=[], schedule=None, start=None, end=None, members=[3,6,9,11,14,17]),
    7: dict(name="Pramuka Penggalang", days=[2], schedule="Rabu", start="12:30", end="13:30", members=PENGGALANG),
}


def activity_day(day, activity_id):
    # School resumes March 30: the Saturday immediately before that is closed too.
    closed = CLOSURES + [(date(2026, 3, 28), date(2026, 3, 29))]
    return (START <= day <= END and day.weekday() in ACTIVITIES[activity_id]["days"]
            and day not in HOLIDAYS and not any(a <= day <= b for a,b in closed))


def build_entries():
    rng = random.Random(2026010120261123)
    school = {(r["attendance_date"],r["student_id"]): r["status"] for r in generate_entries()}
    rows = []
    for n in range((END-START).days+1):
        day = START + timedelta(days=n)
        for aid, activity in ACTIVITIES.items():
            if not activity_day(day, aid):
                continue
            for sid in activity["members"]:
                status = rng.choices(["masuk","sakit","izin","alpa"],[94,3,2,1])[0]
                if school.get((day,sid),"masuk") != "masuk":
                    status = school[(day,sid)]
                rows.append(dict(attendance_date=day,extracurricular_id=aid,student_id=sid,status=status,
                    note=TAG,material="Latihan " + activity["name"] + ": kerja sama dan keterampilan (dummy)"))
    validate(rows)
    return rows


def validate(rows):
    days = [START + timedelta(days=n) for n in range((END-START).days+1)]
    expected = {(day,aid,sid) for day in days for aid,a in ACTIVITIES.items()
                if activity_day(day,aid) for sid in a["members"]}
    assert len(rows) == len(expected)
    assert {(r["attendance_date"],r["extracurricular_id"],r["student_id"]) for r in rows} == expected
    for row in rows:
        aid,sid = row["extracurricular_id"],row["student_id"]
        assert row["status"] in {"masuk","sakit","izin","alpa"}
        assert row["note"] == TAG
        if aid == 1:
            assert 1 <= GRADE[STUDENTS[sid]] <= 3
        if aid == 7:
            assert 4 <= GRADE[STUDENTS[sid]] <= 6
    # A student's overlapping extracurricular sessions would be invalid.
    by_student = {}
    for row in rows:
        key = row["attendance_date"],row["student_id"]
        a = ACTIVITIES[row["extracurricular_id"]]
        for previous in by_student.get(key,[]):
            assert a["end"] <= previous["start"] or previous["end"] <= a["start"]
        by_student.setdefault(key,[]).append(a)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--project",type=Path,default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    rows = build_entries()
    summary = [{"name":a["name"],"schedule":a["schedule"],"members":len(a["members"]),
        "sessions":len({r["attendance_date"] for r in rows if r["extracurricular_id"]==aid}),
        "attendance_records":sum(r["extracurricular_id"]==aid for r in rows)} for aid,a in ACTIVITIES.items()]
    print(json.dumps({"start":str(START),"end":str(END),"activities":summary,"records":len(rows)},ensure_ascii=False))
    if not args.apply:
        return
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extensions import adapt
    config = dotenv_values(args.project/".env")
    demo = config["DASHBOARD_DEMO_DB_NAME"]
    if demo == config["DB_NAME"] or not demo.endswith("_dashboard_demo"):
        raise RuntimeError("Only the separate demo DB may be changed")

    def reader():
        return psycopg2.connect(dbname=demo,user=config["DASHBOARD_DEMO_DB_USER"],
            password=config["DASHBOARD_DEMO_DB_PASS"],host=config["DB_HOST"],port=config["DB_PORT"],
            connect_timeout=5,options="-c default_transaction_read_only=on")

    def query_dicts(cur,statement):
        cur.execute(statement)
        columns=[r[0] for r in cur.description]
        return [dict(zip(columns,row)) for row in cur.fetchall()]

    conn=reader()
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0]==demo
        cur.execute("SELECT id,full_name FROM students ORDER BY id")
        assert cur.fetchall()==[(n,"Siswa Demo "+str(n)) for n in range(1,19)]
        cur.execute("SELECT id,name FROM school_classes ORDER BY id")
        assert all(CLASSES.get(cid)==name for cid,name in cur.fetchall())
        cur.execute("SELECT id,name FROM extracurriculars ORDER BY id")
        existing=cur.fetchall()
        assert existing==[(1,"Pramuka Demo")] or existing==[(i,a["name"]) for i,a in ACTIVITIES.items()]
        daily_before=query_dicts(cur,"SELECT id,attendance_date,student_id,class_id,status FROM attendance_records ORDER BY id")
        assert len(daily_before)==3960
        cur.execute("SELECT md5(jsonb_agg(to_jsonb(t) ORDER BY id)::text) FROM borrowing_records t")
        library_hash=cur.fetchone()[0]
        cur.execute("SELECT count(*),count(*) FILTER (WHERE note=%s) FROM extracurricular_attendance_records",(TAG,))
        count,tagged=cur.fetchone()
        assert count==8 or count==tagged==len(rows)
    conn.close()
    backup=Path(tempfile.mkdtemp(prefix="aska-demo-before-extracurricular-",dir="/root"))
    tables=["school_classes","students","attendance_records","extracurriculars","extracurricular_members",
            "extracurricular_coaches","extracurricular_attendance_records"]
    command=["sudo","-u","postgres","pg_dump","-Fc","--no-owner","--no-acl","-d",demo]
    for table in tables:
        command.extend(["-t","public."+table])
    with (backup/"extracurricular.dump").open("wb") as output:
        subprocess.run(command,cwd="/tmp",stdout=output,check=True)
    literal=lambda value: adapt(value).getquoted().decode()
    statements=["BEGIN;","DO $$ BEGIN IF current_database() <> "+literal(demo)+" THEN RAISE EXCEPTION 'Wrong database'; END IF; END $$;",
        "LOCK TABLE public.students,public.school_classes,public.attendance_records,public.extracurriculars,public.extracurricular_members,public.extracurricular_coaches,public.extracurricular_attendance_records IN EXCLUSIVE MODE;"]
    for cid,name in CLASSES.items():
        statements.append("INSERT INTO school_classes (id,name,academic_year) VALUES (%s,%s,'2026/2027') ON CONFLICT (id) DO NOTHING;"%(cid,literal(name)))
    for sid,cid in STUDENTS.items():
        statements.append("UPDATE students SET class_id=%s WHERE id=%s;"%(cid,sid))
    statements.append("UPDATE attendance_records a SET class_id=s.class_id FROM students s WHERE a.student_id=s.id AND a.class_id<>s.class_id;")
    statements.extend(["DELETE FROM extracurricular_attendance_records;","DELETE FROM extracurricular_members;","DELETE FROM extracurricular_coaches;"])
    for aid,a in ACTIVITIES.items():
        values=",".join(literal(v) for v in (aid,a["name"],"Guru Demo",28,a["schedule"],a["start"],a["end"],"Area Latihan Demo",len(a["members"]),27,27))
        statements.append("INSERT INTO extracurriculars (id,name,coach_name,coach_user_id,schedule_day,start_time,end_time,location,capacity,created_by,updated_by) VALUES ("+values+") ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,schedule_day=EXCLUDED.schedule_day,start_time=EXCLUDED.start_time,end_time=EXCLUDED.end_time,capacity=EXCLUDED.capacity,updated_by=27;")
        statements.append("INSERT INTO extracurricular_coaches (extracurricular_id,coach_user_id,assigned_by) VALUES (%s,28,27);"%aid)
        for sid in a["members"]:
            statements.append("INSERT INTO extracurricular_members (extracurricular_id,student_id,joined_at,note) VALUES (%s,%s,'2026-01-01',%s);"%(aid,sid,literal(TAG)))
    values=[]
    for row in rows:
        timestamp=row["attendance_date"].isoformat()+" "+ACTIVITIES[row["extracurricular_id"]]["end"]+":00+07"
        values.append("("+",".join(literal(v) for v in (row["attendance_date"],row["extracurricular_id"],
            row["student_id"],row["status"],row["note"],row["material"],28,timestamp,timestamp))+")")
    statements.append("INSERT INTO extracurricular_attendance_records (attendance_date,extracurricular_id,student_id,status,note,material,recorded_by,recorded_at,updated_at) VALUES "+",\n".join(values)+";")
    for table in ("school_classes","extracurriculars"):
        statements.append("SELECT setval(pg_get_serial_sequence('public.%s','id'),(SELECT max(id) FROM public.%s));"%(table,table))
    statements.append("COMMIT;")
    subprocess.run(["sudo","-u","postgres","psql","-X","-v","ON_ERROR_STOP=1","-d",demo],
        cwd="/tmp",input="\n".join(statements),text=True,check=True,capture_output=True)
    conn=reader()
    with conn.cursor() as cur:
        committed=query_dicts(cur,"SELECT attendance_date,extracurricular_id,student_id,status,note FROM extracurricular_attendance_records")
        validate(committed)
        key=lambda row:(row["attendance_date"],row["extracurricular_id"],row["student_id"])
        assert sorted(committed,key=key)==sorted(
            [{k:r[k] for k in ("attendance_date","extracurricular_id","student_id","status","note")} for r in rows],key=key)
        daily_after=query_dicts(cur,"SELECT id,attendance_date,student_id,class_id,status FROM attendance_records ORDER BY id")
        assert daily_after==[{**row,"class_id":STUDENTS[row["student_id"]]} for row in daily_before]
        cur.execute("SELECT md5(jsonb_agg(to_jsonb(t) ORDER BY id)::text) FROM borrowing_records t")
        assert cur.fetchone()[0]==library_hash
        cur.execute("SELECT e.extracurricular_id,s.id,c.name FROM extracurricular_members e JOIN students s ON s.id=e.student_id JOIN school_classes c ON c.id=s.class_id WHERE e.extracurricular_id IN (1,7)")
        members=cur.fetchall()
        assert len(members)==18
        for aid,sid,name in members:
            assert (int(name[0])<=3) == (aid==1)
        cur.execute("SELECT extracurricular_id,student_id FROM extracurricular_members WHERE active ORDER BY extracurricular_id,student_id")
        assert cur.fetchall()==sorted((aid,sid) for aid,a in ACTIVITIES.items() for sid in a["members"])
        cur.execute("SELECT id,name FROM school_classes ORDER BY id")
        assert dict(cur.fetchall())==CLASSES
    conn.close()
    print("Applied and verified extracurricular demo history, scouting grades and daily class references. Backup:",backup/"extracurricular.dump")


if __name__=="__main__":
    main()
