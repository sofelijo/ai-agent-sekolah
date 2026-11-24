import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys,types,unittest,tempfile,os
from unittest.mock import patch
from flask import Flask,Blueprint,session
ROOT=Path(__file__).resolve().parents[1]
PACKAGE='bullying_access_fixture';package=types.ModuleType(PACKAGE);package.__path__=[];sys.modules[PACKAGE]=package
spec=importlib.util.spec_from_file_location(PACKAGE+'.bullying',ROOT/'dashboard/bullying.py')
class BullyingAccessTests(unittest.TestCase):
 def setUp(self):
  self.real_role='staff'
  self.attachment={'id':'a'*32,'extension':'png','mime':'image/png','name':'foto.png'}
  self.folder=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BULLYING_EVIDENCE_DIR':self.folder.name});self.env.start()
  (Path(self.folder.name)/('a'*32+'.png')).write_bytes(b'private-evidence')
  fixture=self
  class Cursor:
   def execute(self,*args):self.query=args[0]
   def fetchone(self):return {'role':fixture.real_role} if 'SELECT role' in self.query else {'metadata':{'attachments':[fixture.attachment]}}
  @contextmanager
  def cursor():yield Cursor()
  stub=types.ModuleType(PACKAGE+'.db_access');stub.original_cursor=cursor;sys.modules[stub.__name__]=stub
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  app=Flask(__name__);app.secret_key='test-only';app.add_url_rule('/login','auth.login',lambda:'login')
  bp=Blueprint('main',__name__)
  bp.add_url_rule('/bullying-reports','bullying_reports',lambda:'private list')
  bp.add_url_rule('/bullying-reports/1/status','update_bullying_status',lambda:'saved',methods=['POST'])
  app.register_blueprint(bp);module.init_bullying_dashboard(app);self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']={'id':9,'role':'staff'};s['bullying_admin_csrf']='token'
 def tearDown(self):self.env.stop();self.folder.cleanup()
 def test_evidence_requires_role_and_is_private_download(self):
  url='/bullying-reports/1/evidence/'+self.attachment['id']
  r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertEqual(r.data,b'private-evidence');self.assertIn('attachment;',r.headers['Content-Disposition']);self.assertEqual(r.headers['Cache-Control'],'private, no-store');r.close()
  self.real_role='viewer';self.assertEqual(self.client.get(url).status_code,403)
  with self.client.session_transaction() as s:s.clear()
  self.assertEqual(self.client.get(url).status_code,302)
 def test_unknown_evidence_not_disclosed(self):self.assertEqual(self.client.get('/bullying-reports/1/evidence/'+'b'*32).status_code,404)
 def test_teacher_can_read(self):self.assertEqual(self.client.get('/bullying-reports').status_code,200)
 def test_revoked_role_cannot_read(self):
  self.real_role='viewer';self.assertEqual(self.client.get('/bullying-reports').status_code,403)
 def test_viewer_session_cannot_read(self):
  with self.client.session_transaction() as s:s['user']['role']='viewer';s.modified=True
  self.assertEqual(self.client.get('/bullying-reports').status_code,403)
 def test_anonymous_must_login(self):
  with self.client.session_transaction() as s:s.clear()
  self.assertEqual(self.client.get('/bullying-reports').status_code,302)
 def test_csrf_required_for_teacher_update(self):
  self.assertEqual(self.client.post('/bullying-reports/1/status').status_code,400)
  self.assertEqual(self.client.post('/bullying-reports/1/status',data={'bullying_csrf':'token'}).status_code,200)
 def test_bulk_csrf_header(self):self.assertEqual(self.client.post('/bullying-reports/1/status',headers={'X-Bullying-CSRF':'token'}).status_code,200)
if __name__=='__main__':unittest.main()
