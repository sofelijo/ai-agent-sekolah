"""Access and isolation guards without importing application DB startup hooks."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask, Blueprint, session
from jinja2 import DictLoader

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "preview_guard_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "dashboard")]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + ".data_mode", ROOT / "dashboard/data_mode.py")
mode = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mode
spec.loader.exec_module(mode)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {
            "DASHBOARD_DATA_MODE_ADMINS": "owner@example.invalid",
            "DASHBOARD_DEMO_DB_NAME": "isolated_demo",
        })
        self.env.start()
        self.row = {"email": "owner@example.invalid", "role": "admin"}
        self.demo_available = True
        self.current_mode = "original"
        fixture = self

        class Cursor:
            def execute(self, query, params=None):
                self.query = query
                if query.startswith('UPDATE dashboard_data_mode'):
                    fixture.current_mode = params[0]

            def fetchone(self):
                if 'SELECT mode FROM' in self.query:
                    return {'mode': fixture.current_mode}
                if 'AS pending' in self.query:
                    return {'pending': 0}
                return fixture.row

        @contextmanager
        def original_cursor():
            yield Cursor()

        @contextmanager
        def demo_cursor(pool):
            if not fixture.demo_available:
                raise RuntimeError("offline")
            cursor = Cursor()
            cursor.fetchone = lambda: ("isolated_demo", "on")
            yield cursor

        stub = types.ModuleType(PACKAGE + ".db_access")
        stub.original_cursor = original_cursor
        stub.original_write_cursor = original_cursor
        stub.demo_pool = lambda: object()
        stub._cursor_from_pool = demo_cursor
        sys.modules[stub.__name__] = stub
        self.app = Flask(__name__)
        self.app.secret_key = "test-only-key"
        self.app.jinja_loader = DictLoader({"data_mode.html": "{{ data_mode_token }}"})
        main = Blueprint("main", __name__)

        @main.route("/", methods=["GET", "POST"])
        def app_hub():
            return "dummy" if mode.dummy_requested() else "original"

        self.app.register_blueprint(main)
        mode.init_data_mode(self.app)
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        self.env.stop()

    def login(self, **overrides):
        with self.client.session_transaction() as sess:
            sess["user"] = {
                **dict(id=27, email="owner@example.invalid", role="admin"), **overrides,
            }

    def activate(self, value="dummy"):
        response = self.client.get("/settings/data-mode")
        return self.client.post("/settings/data-mode", data={"csrf_token": response.text, "mode": value})

    def test_original_by_default(self):
        self.assertEqual(self.client.get("/").text, "original")

    def test_switch_is_global_for_logged_in_users_and_reversible(self):
        self.assertEqual(self.activate().status_code, 302)
        self.assertEqual(self.client.get("/").text, "dummy")
        other = self.app.test_client()
        with other.session_transaction() as sess:
            sess['user'] = dict(id=28, email='teacher@example.invalid', role='staff')
        self.assertEqual(other.get('/').text, 'dummy')
        self.assertEqual(self.app.test_client().get('/').text, 'original')
        self.assertEqual(self.activate("original").status_code, 302)
        self.assertEqual(self.client.get("/").text, "original")

    def test_other_admin_cannot_access(self):
        self.login(email="other@example.invalid")
        self.assertEqual(self.client.get("/settings/data-mode").status_code, 404)

    def test_non_admin_cannot_access(self):
        self.login(role="staff")
        self.assertEqual(self.client.get("/settings/data-mode").status_code, 404)

    def test_logged_out_cannot_access(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        self.assertEqual(self.client.get("/settings/data-mode").status_code, 404)

    def test_revoked_real_role_cannot_access(self):
        self.row["role"] = "staff"
        self.assertEqual(self.client.get("/settings/data-mode").status_code, 404)

    def test_forged_identity_cannot_access(self):
        self.row["email"] = "other@example.invalid"
        self.assertEqual(self.client.get("/settings/data-mode").status_code, 404)

    def test_csrf_required(self):
        self.assertEqual(self.client.post("/settings/data-mode", data={"mode": "dummy"}).status_code, 400)

    def test_invalid_mode_rejected(self):
        self.assertEqual(self.activate("invalid").status_code, 400)

    def test_dummy_write_rejected(self):
        self.activate()
        self.assertEqual(self.client.post("/").status_code, 409)
        response = self.client.post('/',headers={'X-Dashboard-Data-Mode':'original'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.text,'original')

    def test_revocation_prevents_global_control_but_not_shared_view(self):
        self.activate()
        self.row["role"] = "staff"
        self.assertEqual(self.client.get('/settings/data-mode').status_code, 404)
        self.assertEqual(self.client.get('/').text, 'dummy')

    def test_unavailable_demo_does_not_switch(self):
        self.demo_available = False
        self.assertEqual(self.activate().status_code, 302)
        self.assertEqual(self.client.get("/").text, "original")

    def test_authenticated_response_not_cached(self):
        self.assertEqual(self.client.get("/").headers["Cache-Control"], "private, no-store")

    def test_stale_dummy_form_cannot_write_after_switch_back(self):
        self.activate()
        self.activate("original")
        self.assertEqual(self.client.post("/", data={"_dashboard_data_mode": "dummy"}).status_code, 409)

    def test_stale_dummy_ajax_cannot_write_after_switch_back(self):
        self.activate()
        self.activate("original")
        self.assertEqual(self.client.post("/", headers={"X-Dashboard-Data-Mode": "dummy"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
