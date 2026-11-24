"""Integration tests in a disposable schema-only DB; run as postgres."""
import sys,subprocess,uuid,os,argparse,io,tempfile
from PIL import Image
from werkzeug.datastructures import FileStorage
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor
# use source schema only, never production rows.
parser=argparse.ArgumentParser();parser.add_argument('--schema-db',required=True);args=parser.parse_args()
source=args.schema_db;name='bullying_test_'+uuid.uuid4().hex[:8]
admin=psycopg2.connect(dbname='postgres');admin.autocommit=True
conn=None
evidence_dir=tempfile.TemporaryDirectory()
os.environ["BULLYING_EVIDENCE_DIR"]=evidence_dir.name
def photo():
 stream=io.BytesIO();Image.new("RGB",(8,8),"red").save(stream,format="PNG");stream.seek(0)
 return FileStorage(stream=stream,filename="foto.png")
try:
 with admin.cursor() as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
 schema=subprocess.check_output(['pg_dump','--schema-only','--no-owner','--no-acl','-d',source],text=True)
 subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','-d',name],input=schema,text=True,stdout=subprocess.DEVNULL,check=True)
 conn=psycopg2.connect(dbname=name)
 @contextmanager
 def cursor(commit=False):
  try:
   with conn.cursor(cursor_factory=DictCursor) as c:yield c
   if commit:conn.commit()
  except:conn.rollback();raise
  finally:conn.rollback()
 from bullying_intake import save_public_report,RateLimited
 # All application connections in this test point at the disposable DB.
 os.environ.update(DB_HOST='/var/run/postgresql',DB_PORT='5432',DB_NAME=name,DB_USER='postgres',DB_PASS='peer-auth-test')
 from dashboard import queries
 from dashboard.db_access import original_cursor
 data=dict(reporter_name='',description='Laporan simulasi khusus pengujian database sementara.',category='verbal',urgent=False,contact='test@example.invalid',victim='Test',student_class='4 D',offender='',location='Halaman',incident_date='2026-11-23',reporter_role='student')
 with patch('dashboard.db_access.original_write_cursor',lambda:cursor(True)),patch.object(queries,'original_cursor',cursor),patch.object(queries,'original_write_cursor',lambda:cursor(True)):
  receipt=save_public_report(data,submission_id='test1',ip_hash='hashed-peer',site_key='default',files=[photo()])
  assert receipt==save_public_report(data,submission_id='test1',ip_hash='another-peer',site_key='default')
  rows,total=queries.fetch_bullying_reports();assert total==1 and rows[0]['username']=='Anonim'
  key=rows[0]['id'];detail=queries.fetch_bullying_report_detail(key);assert len(detail['events'])==1
  assert len(detail['metadata']['attachments'])==1 and len(list(Path(evidence_dir.name).iterdir()))==1
  assert queries.update_bullying_report_status(key,'in_progress',notes='Test follow-up',assigned_to='Guru test',updated_by='Admin test')
  detail=queries.fetch_bullying_report_detail(key);assert detail['status']=='in_progress' and len(detail['events'])==2
  assert queries.bulk_update_bullying_report_status([key],'resolved','Admin test')
  detail=queries.fetch_bullying_report_detail(key);assert detail['resolved_at'] and len(detail['events'])==3
  print('PASS anonymous intake, cross-peer retry idempotency, staff status/notes/assignee and full audit history.')
  @contextmanager
  def failed_commit():
   try:
    with conn.cursor(cursor_factory=DictCursor) as c:yield c
    raise RuntimeError('simulated commit failure')
   finally:conn.rollback()
  with patch('dashboard.db_access.original_write_cursor',failed_commit):
   try:save_public_report(data,submission_id='failed',ip_hash='separate-peer',site_key='default',files=[photo()])
   except RuntimeError:pass
   else:raise AssertionError('Commit failure missing')
  assert len(list(Path(evidence_dir.name).iterdir()))==1 and queries.fetch_bullying_reports()[1]==1
  print('PASS evidence stored once on retry; database commit failure removes uploaded files and report.')
  for index in range(4):save_public_report(data,submission_id='test'+str(index+2),ip_hash='hashed-peer',site_key='default')
  try:save_public_report(data,submission_id='over-limit',ip_hash='hashed-peer',site_key='default')
  except RateLimited:pass
  else:raise AssertionError('Rate limit missing')
  assert queries.fetch_bullying_reports()[1]==5
  print('PASS durable peer rate limit and rollback of rejected submissions; only temporary database changed.')
finally:
 if conn:conn.close()
 if 'dashboard.db_access' in sys.modules:sys.modules['dashboard.db_access'].shutdown_pool()
 if 'db' in sys.modules:sys.modules['db'].conn.close()
 with admin.cursor() as c:c.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
 admin.close()
 evidence_dir.cleanup()
