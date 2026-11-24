"""Durable original-to-demo replication. Never replays demo data to production."""
from datetime import datetime,timedelta,timezone
import re
import time
import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json,RealDictCursor

MASTER_COLUMNS={
 'school_classes':'id,name,academic_year,active,metadata',
 'dashboard_users':'id,email,full_name,role,assigned_class_id,degree_prefix,degree_suffix,jabatan,password_hash',
 'students':'id,class_id,full_name,student_number,sequence,nisn,gender,active,student_status,status_academic_year,exit_date',
 'student_class_history':'id,student_id,academic_year,class_id,class_name,sequence,student_number,nisn,full_name,gender,graduation_date,graduation_status',
 'books':'id,title,author,publisher,year,code,stock,location',
 'book_items':'id,book_id,qr_code,status,is_labeled',
 'extracurriculars':'id,name,coach_name,coach_user_id,schedule_day,start_time,end_time,location,capacity,description,active,created_by,updated_by,metadata',
 'student_violation_categories':None,'student_violation_types':None,'student_point_thresholds':None,
}
NATURAL={
 'attendance_records':('attendance_date','student_id'),
 'teacher_attendance_records':('attendance_date','teacher_id'),
 'extracurricular_attendance_records':('attendance_date','extracurricular_id','student_id'),
 'extracurricular_members':('extracurricular_id','student_id'),
 'extracurricular_coaches':('extracurricular_id','coach_user_id'),
}
ID_TRANSACTIONS={'borrowing_records','attendance_late_students','student_point_records'}
TABLES=tuple(sorted(set(MASTER_COLUMNS)|set(NATURAL)|ID_TRANSACTIONS))
MAPPED_TABLES=set(NATURAL)|ID_TRANSACTIONS
SOURCE_KEYS={t:(('extracurricular_id','coach_user_id') if t=='extracurricular_coaches' else ('id',)) for t in TABLES}
REFERENCES={
 'dashboard_users':{'assigned_class_id':'school_classes'},'students':{'class_id':'school_classes'},
 'student_class_history':{'student_id':'students','class_id':'school_classes'},
 'book_items':{'book_id':'books'},
 'extracurriculars':{'coach_user_id':'dashboard_users','created_by':'dashboard_users','updated_by':'dashboard_users'},
 'extracurricular_members':{'extracurricular_id':'extracurriculars','student_id':'students'},
 'extracurricular_coaches':{'extracurricular_id':'extracurriculars','coach_user_id':'dashboard_users','assigned_by':'dashboard_users'},
 'attendance_records':{'student_id':'students','class_id':'school_classes','teacher_id':'dashboard_users'},
 'teacher_attendance_records':{'teacher_id':'dashboard_users','recorded_by':'dashboard_users'},
 'attendance_late_students':{'class_id':'school_classes','recorded_by':'dashboard_users'},
 'extracurricular_attendance_records':{'extracurricular_id':'extracurriculars','student_id':'students','recorded_by':'dashboard_users'},
 'borrowing_records':{'student_id':'students','book_id':'books','book_item_id':'book_items','recorded_by':'dashboard_users','returned_by':'dashboard_users'},
 'student_point_records':{'student_id':'students','violation_type_id':'student_violation_types','recorded_by':'dashboard_users','voided_by':'dashboard_users'},
}
for _t in ('student_violation_categories','student_violation_types','student_point_thresholds'):
 REFERENCES[_t]={'created_by':'dashboard_users','updated_by':'dashboard_users'}


def connect(config,demo=False):
    return psycopg2.connect(dbname=config['DASHBOARD_DEMO_DB_NAME'] if demo else config['DB_NAME'],
        user=config['DASHBOARD_DEMO_WRITER_USER'] if demo else config['DB_USER'],
        password=config['DASHBOARD_DEMO_WRITER_PASS'] if demo else config['DB_PASS'],
        host=config['DB_HOST'],port=config['DB_PORT'],connect_timeout=8,
        options='-c statement_timeout=20000 -c lock_timeout=5000')


class Replicator:
    def __init__(self,source,destination):
        self.source,self.destination=source,destination
        self.columns={}

    def read(self,table,key):
        if table not in TABLES:raise ValueError('Unsupported sync table')
        where=sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(c)) for c in SOURCE_KEYS[table])
        with self.source.cursor() as cur:
            cur.execute(sql.SQL('SELECT to_jsonb(t) FROM public.{} t WHERE ').format(sql.Identifier(table))+where,
                tuple(key[c] for c in SOURCE_KEYS[table]))
            row=cur.fetchone()
            return row[0] if row else None

    def target_columns(self,table):
        if table not in self.columns:
            with self.destination.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
                self.columns[table]=[r[0] for r in cur.fetchall()]
        return self.columns[table]

    def refresh_item(self,cur,item_id):
        cur.execute("""UPDATE book_items SET status=CASE WHEN EXISTS(
            SELECT 1 FROM borrowing_records WHERE book_item_id=%s AND status='borrowed')
            THEN 'borrowed' ELSE 'available' END WHERE id=%s AND status IN ('available','borrowed')""",(item_id,item_id))

    def upsert(self,table,data,seen=None):
        if seen is None:seen=set()
        identity=(table,tuple(data.get(c) for c in SOURCE_KEYS[table]))
        if identity in seen:return
        seen.add(identity)
        for field,parent in REFERENCES.get(table,{}).items():
            if data.get(field) is not None:
                row=self.read(parent,{'id':data[field]})
                if row:self.upsert(parent,row,seen)
        row=dict(data)
        if table=='dashboard_users':row['password_hash']='!demo-login-disabled'
        if table=='extracurriculars' and row['id']==1:row['name']='Pramuka Siaga'
        if table=='extracurricular_attendance_records' and row.get('extracurricular_id') in (1,7):
            with self.source.cursor() as cur:
                cur.execute("SELECT class_name FROM student_class_history WHERE student_id=%s AND academic_year=to_char(%s::date-INTERVAL '6 months','YYYY')||'/'||to_char(%s::date+INTERVAL '6 months','YYYY')",(row['student_id'],row['attendance_date'],row['attendance_date']))
                historic=cur.fetchone()
            if historic:
                match=re.match(r'\s*([1-6])',historic[0])
                if match:
                    row['extracurricular_id']=1 if int(match[1])<=3 else 7
                    parent=self.read('extracurriculars',{'id':row['extracurricular_id']})
                    if parent:self.upsert('extracurriculars',parent,seen)
        if table=='extracurricular_members' and row.get('extracurricular_id') in (1,7):
            with self.destination.cursor() as cur:
                cur.execute('SELECT c.name FROM students s JOIN school_classes c ON c.id=s.class_id WHERE s.id=%s',(row['student_id'],))
                current=cur.fetchone()
            if current:
                match=re.match(r'\s*([1-6])',current[0])
                if match:row['active']=bool(row['active'] and ((int(match[1])<=3)==(row['extracurricular_id']==1)))
        allowed=MASTER_COLUMNS.get(table)
        columns=[c for c in self.target_columns(table) if c in row and (not allowed or c in allowed.split(','))]
        if table in MAPPED_TABLES:
            if table!='extracurricular_coaches':
                row['source_record_id']=row['id'];columns=[c for c in columns if c!='id']+['source_record_id']
            keys=NATURAL.get(table,('source_record_id',))
        else:keys=('id',)
        with self.destination.cursor() as cur:
            # Existing simulated surrogate IDs must never be used as original IDs.
            if table in NATURAL and table!='extracurricular_coaches':
                where=sql.SQL(' AND ').join(sql.SQL('{} IS NOT DISTINCT FROM %s').format(sql.Identifier(k)) for k in keys)
                cur.execute(sql.SQL('DELETE FROM public.{} WHERE source_record_id=%s AND NOT (').format(sql.Identifier(table))+where+sql.SQL(')'),
                    (row['source_record_id'],)+tuple(row[k] for k in keys))
            if table=='borrowing_records':
                cur.execute("""DELETE FROM borrowing_records WHERE source_record_id IS NULL AND book_item_id=%s
                    AND borrow_date<=COALESCE(%s::date,'infinity'::date)
                    AND COALESCE(return_date,'infinity'::date)>=%s::date""",
                    (row['book_item_id'],row.get('return_date'),row['borrow_date']))
            values=[Json(row[c]) if isinstance(row[c],(dict,list)) else row[c] for c in columns]
            updates=[c for c in columns if c not in keys]
            statement=sql.SQL('INSERT INTO public.{} ({}) VALUES ({}) ON CONFLICT ({}) ').format(
                sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in columns),sql.SQL(',').join(map(sql.Identifier,keys)))
            statement+=sql.SQL('DO UPDATE SET ')+sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(c),sql.Identifier(c)) for c in updates) if updates else sql.SQL('DO NOTHING')
            cur.execute(statement,values)
            if table=='book_items':self.refresh_item(cur,row['id'])
            if table=='borrowing_records':self.refresh_item(cur,row['book_item_id'])

    def delete(self,table,key):
        with self.destination.cursor() as cur:
            if table in MASTER_COLUMNS:
                # Remove only synthetic restricting dependents before a real master deletion.
                for child,refs in REFERENCES.items():
                    if child in MAPPED_TABLES and child!='extracurricular_coaches':
                        for field,parent in refs.items():
                            if parent==table:
                                cur.execute(sql.SQL('DELETE FROM public.{} WHERE {}=%s AND source_record_id IS NULL').format(sql.Identifier(child),sql.Identifier(field)),(key['id'],))
                cur.execute(sql.SQL('DELETE FROM public.{} WHERE id=%s').format(sql.Identifier(table)),(key['id'],))
            elif table in NATURAL:
                keys=NATURAL[table]
                where=sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in keys)
                if table=='extracurricular_coaches':
                    cur.execute(sql.SQL('DELETE FROM public.{} WHERE ').format(sql.Identifier(table))+where,tuple(key[k] for k in keys))
                else:
                    cur.execute(sql.SQL('DELETE FROM public.{} WHERE source_record_id=%s OR (source_record_id IS NULL AND ').format(sql.Identifier(table))+where+sql.SQL(')'),(key['id'],)+tuple(key[k] for k in keys))
            else:
                cur.execute(sql.SQL('DELETE FROM public.{} WHERE source_record_id=%s').format(sql.Identifier(table)),(key['id'],))
            if table=='borrowing_records' and key.get('book_item_id'):self.refresh_item(cur,key['book_item_id'])

    def apply(self,event):
        table=event['table_name'];key=event['row_key']
        row=self.read(table,key)
        # Coalesce stale events to the latest committed original state.
        if row:self.upsert(table,row)
        else:self.delete(table,key)


def run(config,once=False):
    if config['DASHBOARD_DEMO_DB_NAME']==config['DB_NAME']:raise RuntimeError('Separate demo DB required')
    source=connect(config);source.autocommit=True
    destination=connect(config,True)
    with source.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(7831262026)')
        if not cur.fetchone()[0]:raise RuntimeError('Another demo sync worker is running')
    worker=Replicator(source,destination)
    while True:
        with source.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT id,table_name,row_key FROM dashboard_demo_outbox WHERE synced_at IS NULL
                AND (last_attempt_at IS NULL OR last_attempt_at<NOW()-INTERVAL '20 seconds') ORDER BY id LIMIT 100""")
            events=cur.fetchall()
        for event in events:
            try:
                worker.apply(event);destination.commit()
                with source.cursor() as cur:
                    cur.execute('UPDATE dashboard_demo_outbox SET synced_at=NOW(),last_error=NULL WHERE id=%s',(event['id'],))
            except Exception as exc:
                destination.rollback()
                error=type(exc).__name__+':'+str(getattr(exc,'pgcode','') or '')
                with source.cursor() as cur:
                    cur.execute('UPDATE dashboard_demo_outbox SET attempts=attempts+1,last_attempt_at=NOW(),last_error=%s WHERE id=%s',(error,event['id']))
                print('Sync retry:',event['table_name'],event['id'],error,flush=True)
        if once:break
        if not events:time.sleep(2)
