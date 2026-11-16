"""Authentication must track credential changes independently of cookie signing."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.webui import server


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_path = Path(directory.name) / "config.yml"
        self.addCleanup(setattr, server.app, "secret_key", server.app.secret_key)
        server.app.secret_key = os.urandom(24)
        for obj, name, value in (
            (server, "_CONFIG_PATH", self.config_path),
            (server, "_auth_password", None),
            (server, "_auth_generation", ""),
            (server, "_restart_service", lambda: (True, "Test restart.")),
            (server, "_get_current_version", lambda: "test"),
            (server, "_get_after_hours_photo", lambda: ""),
        ):
            mock = patch.object(obj, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.set_password("original-password")
        self.client = server.app.test_client()

    def set_password(self, password):
        server._write_user_config({"webui": {"password": password}})

    def login(self, client=None, password="original-password"):
        response = (client or self.client).post("/login", data={"password": password})
        self.assertEqual(response.status_code, 302)
        return response

    def test_first_old_session_request_cannot_read_replacement_password(self):
        self.login()
        signing_key = server.app.secret_key
        self.set_password("replacement-password")
        response = self.client.get("/config")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/login"))
        self.assertNotIn(b"replacement-password", response.data)
        self.assertEqual(server.app.secret_key, signing_key)

    def test_flash_route_cannot_promote_stale_session(self):
        self.login()
        self.set_password("replacement-password")
        with patch.object(server, "_fetch_pending_commits") as fetch:
            response = self.client.get("/update/check")
        self.assertTrue(response.location.endswith("/login"))
        fetch.assert_not_called()
        self.assertEqual(self.client.get("/config").status_code, 302)

    def test_password_save_revokes_both_browsers_and_new_login_works(self):
        administrator = server.app.test_client()
        self.login(administrator)
        self.login()
        response = administrator.post("/config", data={"webui__password": "replacement-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/config").status_code, 302)
        self.assertEqual(administrator.get("/config").status_code, 302)
        self.login(administrator, "replacement-password")
        self.assertEqual(administrator.get("/config").status_code, 200)

    def test_all_protected_routes_reject_stale_authentication(self):
        routes = (
            ("GET", "/config"), ("POST", "/config"),
            ("GET", "/modules"), ("POST", "/modules"),
            ("POST", "/location/search"), ("POST", "/after-hours/upload"),
            ("POST", "/after-hours/delete"), ("GET", "/update/check"),
            ("GET", "/update/stream"), ("GET", "/update/status"), ("POST", "/update"),
        )
        for method, path in routes:
            with self.subTest(method=method, path=path):
                self.set_password("original-password")
                self.login()
                self.set_password("replacement-password")
                response = self.client.open(path, method=method)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith("/login"))

    def test_direct_yaml_password_change_is_observed_before_authorization(self):
        self.login()
        self.config_path.write_text(yaml.safe_dump({"webui": {"password": "edited-password"}}))
        self.assertEqual(self.client.get("/config").status_code, 302)
        self.login(password="edited-password")
        self.assertEqual(self.client.get("/config").status_code, 200)

    def test_disabling_and_reenabling_same_password_revokes_old_session(self):
        self.login()
        self.set_password("")
        # No intervening browser request: both writes must still be observed.
        self.set_password("original-password")
        self.assertEqual(self.client.get("/config").status_code, 302)

    def test_password_change_back_does_not_restore_old_session(self):
        self.login()
        self.set_password("temporary-password")
        self.set_password("original-password")
        self.assertEqual(self.client.get("/config").status_code, 302)

    def test_unrelated_save_keeps_current_session_valid(self):
        self.login()
        self.client.post("/config", data={"location__location_name": "Studio"})
        self.assertEqual(self.client.get("/config").status_code, 200)

    def test_legacy_or_malformed_authentication_is_rejected(self):
        for generation in (None, 123, "incorrect-generation"):
            with self.subTest(generation=generation):
                with self.client.session_transaction() as session:
                    session["authenticated"] = True
                    if generation is not None:
                        session["auth_generation"] = generation
                self.assertEqual(self.client.get("/config").status_code, 302)

    def test_wrong_password_and_logout_reject_access(self):
        response = self.client.post("/login", data={"password": "incorrect"})
        self.assertIn(b"Incorrect password", response.data)
        self.assertEqual(self.client.get("/config").status_code, 302)
        self.login()
        self.assertEqual(self.client.get("/config").status_code, 200)
        self.client.get("/logout")
        self.assertEqual(self.client.get("/config").status_code, 302)

    def test_unicode_password_can_log_in_on_first_request(self):
        self.set_password("café-☃")
        self.login(password="café-☃")
        self.assertEqual(self.client.get("/config").status_code, 200)

    def test_open_mode_remains_available_and_enabling_auth_requires_login(self):
        self.set_password("")
        self.assertEqual(self.client.get("/config").status_code, 200)
        self.assertEqual(self.client.get("/modules").status_code, 200)
        self.set_password("original-password")
        self.assertEqual(self.client.get("/config").status_code, 302)

    def test_process_restart_invalidates_previous_cookies(self):
        self.login()
        server.app.secret_key = os.urandom(24)
        self.assertEqual(self.client.get("/config").status_code, 302)
        self.login()
        self.assertEqual(self.client.get("/config").status_code, 200)


if __name__ == "__main__":
    unittest.main()
