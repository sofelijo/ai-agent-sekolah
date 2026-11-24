import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
from flask import Flask
from bullying_intake import RateLimited
from bullying_evidence import EvidenceError
from tests.test_bullying_evidence import photo
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_bullying_test_module',ROOT/'landingpage/bullying.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PublicBullyingTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__,template_folder=str(ROOT/'landingpage/templates'));self.app.secret_key='test-only'
        self.app.config['TESTING']=True
        self.app.add_url_rule('/','landing_home',lambda:'Home')
        self.save=Mock(return_value='BL-0123456789ABCDEF')
        module.register_bullying(self.app,save_report=self.save,fetch_content=lambda **kw:{'site_name':'Test school'},resolve_site_key=lambda:'default')
        self.client=self.app.test_client();self.client.get('/lapor-bullying')
    def payload(self,**changes):
        with self.client.session_transaction() as s:data={'csrf_token':s['bullying_csrf'],'submission_id':s['bullying_submission']}
        data.update(reporter_role='student',location='Halaman sekolah',description='Saya melihat teman diejek berulang kali di halaman.',category='verbal',consent='yes')
        data.update(changes);return data
    def test_form_public_and_does_not_list_students(self):
        r=self.client.get('/lapor-bullying');self.assertEqual(r.status_code,200);self.assertIn('Nama boleh dikosongkan',r.text);self.assertEqual(r.headers['Cache-Control'],'no-store')
    def test_anonymous_report_and_private_receipt(self):
        r=self.client.post('/lapor-bullying',data=self.payload(),follow_redirects=True)
        self.assertEqual(r.status_code,200);self.assertIn('BL-0123456789ABCDEF',r.text)
        args=self.save.call_args;self.assertEqual(args.args[0]['reporter_name'],'');self.assertEqual(len(args.kwargs['ip_hash']),64)
        self.assertNotIn('Saya melihat teman',r.text)
    def test_names_and_contact_are_not_saved_in_cookie(self):
        r=self.client.post('/lapor-bullying',data=self.payload(reporter_name='Private Name',contact='secret@example.invalid'))
        with self.client.session_transaction() as s:self.assertNotIn('Private Name',str(dict(s)));self.assertNotIn('secret@example.invalid',str(dict(s)))
    def test_csrf_rejected(self):
        self.assertEqual(self.client.post('/lapor-bullying',data=self.payload(csrf_token='wrong')).status_code,400);self.save.assert_not_called()
    def test_foreign_submission_rejected(self):
        self.assertEqual(self.client.post('/lapor-bullying',data=self.payload(submission_id='wrong')).status_code,400)
    def test_expired_form(self):
        with self.client.session_transaction() as s:s['bullying_issued']=1
        self.assertEqual(self.client.post('/lapor-bullying',data=self.payload()).status_code,400)
    def test_invalid_fields(self):
        for change in [{'description':'short'},{'category':'invalid'},{'incident_date':'2099-01-01'},{'consent':''},{'contact':'x'*151}]:
            with self.subTest(change=change):self.assertEqual(self.client.post('/lapor-bullying',data=self.payload(**change)).status_code,422)
        self.save.assert_not_called()
    def test_honeypot(self):
        self.assertEqual(self.client.post('/lapor-bullying',data=self.payload(website='spam')).status_code,400);self.save.assert_not_called()
    def test_unavailable_database_does_not_claim_success(self):
        self.save.side_effect=RuntimeError('offline')
        r=self.client.post('/lapor-bullying',data=self.payload());self.assertEqual(r.status_code,503);self.assertIn('Laporan belum tersimpan',r.text)
    def test_upload_reaches_storage(self):
        payload=self.payload();payload['evidence']=photo()
        r=self.client.post('/lapor-bullying',data=payload,content_type='multipart/form-data');self.assertEqual(r.status_code,303)
        self.assertEqual(self.save.call_args.kwargs['files'][0].filename,'foto.png')
    def test_bad_media_returns_validation_error(self):
        self.save.side_effect=EvidenceError('Video rusak')
        r=self.client.post('/lapor-bullying',data=self.payload());self.assertEqual(r.status_code,422);self.assertIn('Video rusak',r.text)
    def test_large_request_has_useful_error(self):
        self.app.config['MAX_CONTENT_LENGTH']=100
        r=self.client.post('/lapor-bullying',data=self.payload());self.assertEqual(r.status_code,413);self.assertIn('20 MB',r.text)
    def test_rate_limit(self):
        self.save.side_effect=RateLimited()
        r=self.client.post('/lapor-bullying',data=self.payload());self.assertEqual(r.status_code,429);self.assertEqual(r.headers['Retry-After'],'600')
    def test_script_text_escaped_on_error(self):
        r=self.client.post('/lapor-bullying',data=self.payload(reporter_name='<script>alert(1)</script>',consent=''))
        self.assertNotIn('<script>alert(1)</script>',r.text);self.assertIn('&lt;script&gt;',r.text)
    def test_success_page_not_shared_between_visitors(self):
        r=self.app.test_client().get('/lapor-bullying/terkirim');self.assertEqual(r.status_code,302);self.assertNotIn('BL-',r.text)
if __name__=='__main__':unittest.main()
