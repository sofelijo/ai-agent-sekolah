from copy import deepcopy
from datetime import date, datetime, timedelta
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("standalone_graduation_test", ROOT / "landingpage/graduation.py")
graduation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graduation)


class LandingGraduationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.static = Path(self.folder.name)
        self.pdf = self.static / "landingpage/uploads/graduations/result.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"%PDF-1.4\nunit-test-only\n")
        self.record = dict(id=1, site_key="default", nisn="0123456789", nama_siswa="Siswa Uji",
            kelas="6 A", tahun_lulus=2026, status="lulus", tanggal_pengumuman=date(2026,6,2),
            pesan_aska="Pesan sekolah.", is_active=True,
            metadata={"document":{"relative_path":"landingpage/uploads/graduations/result.pdf","original_name":"SKL siswa.pdf"}})
        self.app = Flask(__name__, template_folder=str(ROOT / "landingpage/templates"),static_folder=str(self.static))
        self.app.secret_key = "unit-test-only"
        self.app.config["TESTING"] = True
        self.app.add_url_rule("/", "landing_home", lambda: "Home")
        self.lookup_calls = []
        def by_nisn(site_key, nisn, active_only=True):
            self.lookup_calls.append(nisn)
            return deepcopy(self.record) if nisn == self.record["nisn"] else None
        graduation.register_graduation(self.app, fetch_content=lambda **kw:{"site_name":"Sekolah Uji"},
            lookup_by_nisn=by_nisn,
            lookup_by_id=lambda rec_id,site:deepcopy(self.record) if rec_id==1 and site=="default" else None,
            resolve_site_key=lambda:"default")
        self.time = patch.object(graduation,"current_wib",return_value=datetime(2026,11,23,10,tzinfo=graduation.WIB))
        self.time.start()
        self.client = self.app.test_client()

    def tearDown(self):
        self.time.stop()
        self.folder.cleanup()

    def check_student(self):
        return self.client.post("/kelulusan", data={"nisn":"0123456789"},base_url="https://localhost")

    def test_plain_form_has_no_chat_dependency(self):
        response=self.client.get("/kelulusan")
        self.assertEqual(response.status_code,200)
        self.assertIn('action="/kelulusan"',response.text)
        self.assertNotIn("/api/kelulusan/chat",response.text)
        self.assertNotIn("Siswa Uji",response.text)

    def test_valid_nisn_shows_existing_result_and_document_actions(self):
        response=self.check_student()
        self.assertEqual(response.status_code,200)
        self.assertIn("Siswa Uji",response.text)
        self.assertIn("LULUS",response.text)
        self.assertIn("******6789",response.text)
        self.assertIn("Unduh SKL",response.text)
        self.assertIn("Secure",response.headers["Set-Cookie"])
        self.assertIn("HttpOnly",response.headers["Set-Cookie"])

    def test_malformed_nisn_never_calls_lookup(self):
        for nisn in ("", "123", "012345678a", "٠١٢٣٤٥٦٧٨٩"):
            response=self.client.post("/kelulusan",data={"nisn":nisn})
            self.assertIn("tepat 10 digit",response.text)
        self.assertEqual(self.lookup_calls,[])

    def test_unknown_nisn(self):
        response=self.client.post("/kelulusan",data={"nisn":"9999999999"})
        self.assertIn("tidak ditemukan",response.text)
        self.assertNotIn("Siswa Uji",response.text)

    def test_no_document_before_lookup(self):
        for path in ("/kelulusan/surat","/kelulusan/surat/lihat"):
            self.assertEqual(self.client.get(path).status_code,403)

    def test_session_bound_download_and_preview(self):
        self.check_student()
        response=self.client.get("/kelulusan/surat",base_url="https://localhost")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.mimetype,"application/pdf")
        self.assertIn("attachment",response.headers["Content-Disposition"])
        response.close()
        response=self.client.get("/kelulusan/surat/lihat",base_url="https://localhost")
        self.assertEqual(response.status_code,200)
        self.assertIn("inline",response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-Frame-Options"],"SAMEORIGIN")
        response.close()
        self.assertEqual(self.app.test_client().get("/kelulusan/surat").status_code,403)

    def test_new_invalid_lookup_revokes_previous_document_access(self):
        self.check_student()
        self.client.post("/kelulusan",data={"nisn":"bad"},base_url="https://localhost")
        self.assertEqual(self.client.get("/kelulusan/surat",base_url="https://localhost").status_code,403)

    def test_access_expires(self):
        self.check_student()
        with patch.object(graduation,"current_wib",return_value=datetime(2026,11,23,10,16,tzinfo=graduation.WIB)):
            self.assertEqual(self.client.get("/kelulusan/surat",base_url="https://localhost").status_code,403)

    def test_inactive_record_cannot_be_downloaded_with_old_session(self):
        self.check_student()
        self.record["is_active"]=False
        self.assertEqual(self.client.get("/kelulusan/surat",base_url="https://localhost").status_code,403)

    def test_future_announcement_not_disclosed(self):
        self.record["tanggal_pengumuman"]=date(2027,6,2)
        response=self.check_student()
        self.assertIn("belum dibuka",response.text)
        self.assertNotIn("Siswa Uji",response.text)

    def test_missing_document_still_shows_result(self):
        self.pdf.unlink()
        response=self.check_student()
        self.assertIn("Siswa Uji",response.text)
        self.assertIn("belum tersedia",response.text)
        self.assertNotIn("Unduh SKL",response.text)

    def test_traversal_and_symlink_escape_are_rejected(self):
        self.record["metadata"]["document"]["relative_path"]="landingpage/uploads/graduations/../../../outside.pdf"
        self.assertIsNone(graduation.document_path(self.record,self.static))
        outside=self.static.parent/(self.static.name+"-outside.pdf")
        try:
            outside.write_bytes(b"private")
            link=self.pdf.parent/"escape.pdf"
            link.symlink_to(outside)
            self.record["metadata"]["document"]["relative_path"]="landingpage/uploads/graduations/escape.pdf"
            self.assertIsNone(graduation.document_path(self.record,self.static))
        finally:
            outside.unlink(missing_ok=True)

    def test_result_text_is_escaped(self):
        self.record["pesan_aska"]="<script>alert(1)</script>"
        response=self.check_student()
        self.assertNotIn("<script>alert(1)</script>",response.text)
        self.assertIn("&lt;script&gt;",response.text)

    def test_countdown_stays_on_school_domain(self):
        with patch.object(graduation,"current_wib",return_value=datetime(2026,6,1,tzinfo=graduation.WIB)):
            response=self.client.get("/kelulusan")
        self.assertIn("Pengumuman Kelulusan",response.text)
        self.assertNotIn("aska.sdnsembar01.sch.id",response.text)

    def test_aliases_and_cache_headers(self):
        for path in ("/cek-kelulusan","/lp/kelulusan"):
            response=self.client.get(path)
            self.assertEqual(response.status_code,301)
            self.assertEqual(response.headers["Location"],"/kelulusan")
        response=self.check_student()
        self.assertIn("no-store",response.headers["Cache-Control"])
        self.assertEqual(response.headers["X-Robots-Tag"],"noindex, noarchive")


if __name__=="__main__":unittest.main()
