"""Integration tests in two temporary schema-only databases; no production rows copied.

Run as postgres with --schema-db pointing at the project's schema source.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg2
from psycopg2 import sql
from demo_replication import Replicator,MAPPED_TABLES


def main():
    p=argparse.ArgumentParser();p.add_argument('--schema-db',required=True);args=p.parse_args()
    token=uuid.uuid4().hex[:8];names=['aska_sync_test_src_'+token,'aska_sync_test_dst_'+token]
    admin=psycopg2.connect(dbname='postgres');admin.autocommit=True
    src=dst=None
    try:
        schema=subprocess.check_output(['pg_dump','--schema-only','--no-owner','--no-acl','-d',args.schema_db],text=True,cwd='/tmp')
        for name in names:
            with admin.cursor() as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            result=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','-d',name],input=schema,text=True,capture_output=True,cwd='/tmp')
            assert result.returncode==0,'Temporary schema restore failed'
        src=psycopg2.connect(dbname=names[0]);src.autocommit=True
        dst=psycopg2.connect(dbname=names[1])
        with dst.cursor() as c:
            for table in MAPPED_TABLES-{'extracurricular_coaches'}:
                c.execute(sql.SQL('ALTER TABLE {} ADD COLUMN IF NOT EXISTS source_record_id BIGINT UNIQUE').format(sql.Identifier(table)))
        dst.commit()
        with src.cursor() as c:
            c.execute("INSERT INTO school_classes(id,name,academic_year) VALUES (1,'1 A','2026/2027'),(11,'4 A','2026/2027')")
            c.execute("INSERT INTO dashboard_users(id,email,full_name,password_hash,role,assigned_class_id) VALUES (1,'test@example.invalid','Teacher test','secret-never-replicated','staff',11)")
            c.execute("INSERT INTO students(id,class_id,full_name,student_status) VALUES(1,11,'Student test','aktif')")
            c.execute("INSERT INTO student_class_history(student_id,academic_year,class_id,class_name,full_name) VALUES(1,'2026/2027',11,'4 A','Student test')")
            c.execute("INSERT INTO extracurriculars(id,name,coach_user_id) VALUES(1,'Pramuka siaga dan penggalang',1),(7,'Pramuka Penggalang',1)")
            c.execute("INSERT INTO books(id,code,title) VALUES(1,'SYNC-TEST','Test book')")
            c.execute("INSERT INTO book_items(id,book_id,qr_code) VALUES(1,1,'SYNC-TEST-1')")
            c.execute("INSERT INTO student_violation_types(id,code,name,category,points) VALUES(1,'SYNC','Test violation','Test category',5)")
            c.execute("INSERT INTO attendance_records(id,attendance_date,student_id,class_id,teacher_id,status) VALUES(99,'2026-11-23',1,11,1,'masuk')")
        worker=Replicator(src,dst)
        worker.upsert('dashboard_users',worker.read('dashboard_users',{'id':1}))
        worker.upsert('students',worker.read('students',{'id':1}));dst.commit()
        with dst.cursor() as c:
            c.execute("INSERT INTO attendance_records(attendance_date,student_id,class_id,teacher_id,status,note) VALUES('2026-11-23',1,11,1,'alpa','DUMMY') RETURNING id")
            dummy_id=c.fetchone()[0]
        dst.commit()
        event={'table_name':'attendance_records','row_key':{'id':99,'attendance_date':'2026-11-23','student_id':1}}
        worker.apply(event);dst.commit();worker.apply(event);dst.commit()
        with dst.cursor() as c:
            c.execute('SELECT id,status,source_record_id FROM attendance_records');assert c.fetchall()==[(dummy_id,'masuk',99)]
            c.execute('SELECT password_hash FROM dashboard_users WHERE id=1');assert c.fetchone()[0]=='!demo-login-disabled'
        with src.cursor() as c:c.execute("UPDATE attendance_records SET status='izin' WHERE id=99")
        worker.apply(event);dst.commit()
        with dst.cursor() as c:
            c.execute('SELECT count(*),min(status) FROM attendance_records');assert c.fetchone()==(1,'izin')
        other=psycopg2.connect(dbname=names[0])
        try:
            with other.cursor() as c:c.execute("INSERT INTO attendance_records(id,attendance_date,student_id,class_id,teacher_id,status) VALUES(100,'2026-11-24',1,11,1,'masuk')")
            assert worker.read('attendance_records',{'id':100}) is None
            other.rollback()
        finally:other.close()
        with src.cursor() as c:c.execute('DELETE FROM attendance_records WHERE id=99')
        worker.apply(event);dst.commit()
        with dst.cursor() as c:c.execute('SELECT count(*) FROM attendance_records');assert c.fetchone()[0]==0
        print('PASS attendance overwrite/idempotency/update/delete; uncommitted rows invisible; passwords excluded.',flush=True)
        with src.cursor() as c:
            c.execute("INSERT INTO extracurricular_attendance_records(id,attendance_date,extracurricular_id,student_id,status,recorded_by) VALUES(88,'2026-11-18',1,1,'masuk',1)")
        worker.apply({'table_name':'extracurricular_attendance_records','row_key':{'id':88}});dst.commit()
        with dst.cursor() as c:
            c.execute('SELECT extracurricular_id,status,source_record_id FROM extracurricular_attendance_records');assert c.fetchone()==(7,'masuk',88)
        print('PASS extracurricular sync and dated Pramuka grade classification.',flush=True)
        worker.upsert('book_items',worker.read('book_items',{'id':1}));dst.commit()
        with dst.cursor() as c:c.execute("INSERT INTO borrowing_records(student_id,book_id,book_item_id,borrow_date,status) VALUES(1,1,1,'2026-11-19','borrowed')")
        dst.commit()
        with src.cursor() as c:c.execute("INSERT INTO borrowing_records(id,student_id,book_id,book_item_id,borrow_date,status,recorded_by) VALUES(77,1,1,1,'2026-11-20','borrowed',1)")
        event={'table_name':'borrowing_records','row_key':{'id':77,'book_item_id':1}}
        worker.apply(event);dst.commit();worker.apply(event);dst.commit()
        with dst.cursor() as c:
            c.execute('SELECT count(*),min(source_record_id) FROM borrowing_records');assert c.fetchone()==(1,77)
            c.execute('SELECT status FROM book_items WHERE id=1');assert c.fetchone()[0]=='borrowed'
        with src.cursor() as c:c.execute("UPDATE borrowing_records SET status='returned',return_date='2026-11-23' WHERE id=77")
        worker.apply(event);dst.commit()
        with dst.cursor() as c:c.execute('SELECT status FROM book_items WHERE id=1');assert c.fetchone()[0]=='available'
        print('PASS real book loans replace overlapping simulated loans; returns restore availability.',flush=True)
        with dst.cursor() as c:
            c.execute("INSERT INTO student_point_records(student_id,violation_code,violation_name,category,points,occurred_at) VALUES(1,'DUMMY','Dummy','Dummy',5,NOW()) RETURNING id")
            fake_point_id=c.fetchone()[0]
        dst.commit()
        with src.cursor() as c:c.execute("INSERT INTO student_point_records(id,student_id,violation_type_id,violation_code,violation_name,category,points,occurred_at,recorded_by) VALUES(1,1,1,'SYNC','Test violation','Test category',5,NOW(),1)")
        event={'table_name':'student_point_records','row_key':{'id':1}}
        worker.apply(event);dst.commit();worker.apply(event);dst.commit()
        with dst.cursor() as c:
            c.execute('SELECT count(*) FROM student_point_records');assert c.fetchone()[0]==2
            c.execute('SELECT id FROM student_point_records WHERE source_record_id=1');assert c.fetchone()[0]!=fake_point_id
        print('PASS transaction source-ID mapping prevents surrogate-ID collision.',flush=True)
    finally:
        if src:src.close()
        if dst:dst.close()
        for name in names:
            with admin.cursor() as c:c.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
        admin.close()


if __name__=='__main__':main()
