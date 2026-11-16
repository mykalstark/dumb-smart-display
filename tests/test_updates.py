"""Update failures and retries without Git, pip, sudo, or systemd side effects."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.webui import server


def install_result(ok, message="Installer output"):
    yield message
    return ok


class UpdateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.mocks = {}
        for name, kwargs in {
            "_CONFIG_PATH": {"new": self.root / "config.yml"},
            "_configured_password": {"return_value": ""},
            "_get_current_branch": {"return_value": "main"},
            "_get_head_commit": {"side_effect": ["before", "after"]},
            "_fetch_pending_commits": {"return_value": (True, ["new commit"], "")},
            "_do_git_pull": {"return_value": (True, "Updated")},
            "_run_install": {"side_effect": lambda *_: install_result(True)},
            "_restart_service": {"return_value": (True, "Restarted")},
            "_display_service_active": {"return_value": True},
            "_schedule_restart": {},
        }.items():
            mock = patch.object(server, name, **kwargs)
            self.mocks[name] = mock.start()
            self.addCleanup(mock.stop)
        self.client = server.app.test_client()

    def stream(self):
        with self.client.get("/update/stream") as response:
            self.assertEqual(response.status_code, 200)
            return response.get_data(as_text=True)

    def test_install_failure_never_restarts_and_retries_at_same_head(self):
        self.mocks["_run_install"].side_effect = lambda *_: install_result(False, "offline")
        body = self.stream()
        self.assertIn("event: fail", body)
        self.assertNotIn("event: success", body)
        self.assertNotIn("event: restarting", body)
        self.mocks["_restart_service"].assert_not_called()
        self.mocks["_schedule_restart"].assert_not_called()
        self.assertEqual(server._read_update_state()["base"], "before")

        self.mocks["_get_head_commit"].side_effect = ["after", "after"]
        self.mocks["_fetch_pending_commits"].return_value = (True, [], "")
        self.mocks["_run_install"].side_effect = lambda *_: install_result(True)
        body = self.stream()
        self.assertIn("event: restarting", body)
        self.assertNotIn("event: uptodate", body)
        self.mocks["_run_install"].assert_called_with("before", "after")
        self.mocks["_restart_service"].assert_called_once()

    def test_no_javascript_update_uses_same_failure_gates(self):
        self.mocks["_run_install"].side_effect = lambda *_: install_result(False)
        response = self.client.post("/update")
        self.assertEqual(response.status_code, 302)
        self.mocks["_restart_service"].assert_not_called()
        self.mocks["_schedule_restart"].assert_not_called()
        with self.client.session_transaction() as session:
            self.assertEqual(session["_flashes"][-1][0], "error")
        self.assertTrue(server._update_state_path().exists())

    def test_already_current_without_pending_work_does_not_install(self):
        self.mocks["_get_head_commit"].side_effect = ["same", "same"]
        self.mocks["_fetch_pending_commits"].return_value = (True, [], "")
        self.assertIn("event: uptodate", self.stream())
        self.mocks["_run_install"].assert_not_called()
        self.mocks["_restart_service"].assert_not_called()
        self.assertFalse(server._update_state_path().exists())

    def test_restart_failure_and_inactive_display_keep_update_pending(self):
        for restart_ok, active in ((False, True), (True, False)):
            with self.subTest(restart_ok=restart_ok, active=active):
                self.mocks["_get_head_commit"].side_effect = ["before", "after"]
                self.mocks["_restart_service"].return_value = (restart_ok, "Restart result")
                self.mocks["_display_service_active"].return_value = active
                self.assertIn("event: fail", self.stream())
                self.mocks["_schedule_restart"].assert_not_called()
                self.assertTrue(server._update_state_path().exists())

    def test_success_requires_new_web_process_and_display_health(self):
        self.assertIn("event: restarting", self.stream())
        self.assertEqual(self.client.get("/update/status").json["phase"], "restarting")
        self.mocks["_get_head_commit"].side_effect = None
        self.mocks["_get_head_commit"].return_value = "after"
        with patch.object(server, "_UPDATE_INSTANCE", "new-instance"):
            self.mocks["_display_service_active"].return_value = False
            self.assertEqual(self.client.get("/update/status").json["phase"], "failed")
            self.assertTrue(server._update_state_path().exists())
            state = server._read_update_state()
            state["phase"] = "restarting"
            server._write_update_state(state)
            self.mocks["_display_service_active"].return_value = True
            self.assertEqual(self.client.get("/update/status").json["phase"], "complete")
        self.assertFalse(server._update_state_path().exists())

    def test_login_after_restart_finishes_pending_health_check(self):
        self.assertIn("event: restarting", self.stream())
        self.mocks["_configured_password"].return_value = "test-password"
        self.client.post("/login", data={"password": "test-password"})
        self.mocks["_get_head_commit"].side_effect = None
        self.mocks["_get_head_commit"].return_value = "after"
        with patch.dict(server.app.config, SECRET_KEY="new-process-key"), \
             patch.object(server, "_UPDATE_INSTANCE", "new-instance"), \
             patch.object(server, "_get_current_version", return_value="test-version"):
            self.assertEqual(self.client.get("/update/status").status_code, 302)
            self.assertTrue(server._update_state_path().exists())
            response = self.client.post("/login", data={"password": "test-password"}, follow_redirects=True)
            self.assertIn(b"Update complete. The display and control panel are available.", response.data)
            self.assertFalse(server._update_state_path().exists())

    def test_concurrent_update_is_rejected(self):
        server._UPDATE_LOCK.acquire()
        try:
            self.assertIn("An update is already running", self.stream())
        finally:
            server._UPDATE_LOCK.release()
        self.mocks["_fetch_pending_commits"].assert_not_called()

    def test_multiline_installer_output_is_valid_sse(self):
        self.assertEqual(server._sse("one\ntwo", "fail"), "event: fail\ndata: one\ndata: two\n\n")

    def test_root_repair_state_is_owned_by_application_account(self):
        account = SimpleNamespace(pw_uid=1001, pw_gid=1002)
        config = self.root / "new-config" / "config.yml"
        with patch.object(server, "_CONFIG_PATH", config), \
             patch.object(server.os, "geteuid", return_value=0), \
             patch.object(server, "_application_user", return_value="displayuser"), \
             patch("pwd.getpwnam", return_value=account), \
             patch.object(server.os, "chown") as chown, \
             patch.object(server.os, "fchown") as fchown:
            server._write_update_state({"phase": "restarting"})
            chown.assert_called_once_with(config.parent, 1001, 1002)
            self.assertEqual(fchown.call_args.args[1:], (1001, 1002))
            self.assertEqual(server._read_update_state()["phase"], "restarting")
            chown.reset_mock()
            server._write_update_state({"phase": "failed"})
            chown.assert_not_called()


class InstallDispatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = patch.object(server, "_CONFIG_PATH", Path(directory.name) / "config.yml")
        config.start()
        self.addCleanup(config.stop)

    def run_installer(self):
        generator = server._run_install("before", "after")
        output = []
        while True:
            try:
                output.append(next(generator))
            except StopIteration as finished:
                return finished.value, output

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_system_install_changed", return_value=False)
    @patch.object(server, "_pip_install", return_value=(True, "Installed"))
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=1))
    @patch.object(server.subprocess, "Popen")
    def test_limited_sudo_allows_python_only_update_when_system_files_unchanged(self, popen, run, pip, changed, user):
        ok, output = self.run_installer()
        self.assertTrue(ok)
        self.assertIn("Python dependencies only", output[0])
        pip.assert_called_once()
        popen.assert_not_called()

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_system_install_changed", return_value=True)
    @patch.object(server, "_pip_install")
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=1))
    def test_system_changes_require_full_installer(self, run, pip, changed, user):
        ok, output = self.run_installer()
        self.assertFalse(ok)
        self.assertIn("over SSH", output[0])
        pip.assert_not_called()

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_system_install_changed", return_value=True)
    @patch.object(server, "_pip_install", return_value=(True, "Installed"))
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=1))
    def test_manual_install_receipt_allows_retry_of_exact_revision(self, run, pip, changed, user):
        receipt = server._CONFIG_PATH.parent / ".system-install-revision"
        receipt.write_text("older\n")
        self.assertFalse(self.run_installer()[0])
        pip.assert_not_called()
        receipt.write_text("after\n")
        self.assertTrue(self.run_installer()[0])
        pip.assert_called_once()

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_pip_install")
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=0))
    @patch.object(server.subprocess, "Popen")
    def test_real_installer_failure_never_falls_back_and_passes_app_user(self, popen, run, pip, user):
        popen.return_value = MagicMock(stdout=io.StringIO(server._INSTALL_STARTED + "\nfailed\n"), returncode=1)
        popen.return_value.poll.return_value = 1
        ok, output = self.run_installer()
        self.assertFalse(ok)
        self.assertIn("Services were not restarted", output[-1])
        pip.assert_not_called()
        self.assertEqual(popen.call_args.args[0][-3:], ["--update", "--app-user", "displayuser"])

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_system_install_changed", return_value=False)
    @patch.object(server, "_pip_install", return_value=(True, "Installed"))
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=0))
    @patch.object(server.subprocess, "Popen")
    def test_sudo_listing_permission_does_not_imply_passwordless_execution(self, popen, run, pip, changed, user):
        popen.return_value = MagicMock(stdout=io.StringIO("sudo: a password is required\n"), returncode=1)
        popen.return_value.poll.return_value = 1
        ok, output = self.run_installer()
        self.assertTrue(ok)
        self.assertIn("Python dependencies only", output[-2])
        pip.assert_called_once()

    @patch.object(server, "_application_user", return_value="displayuser")
    @patch.object(server, "_system_install_changed", return_value=False)
    @patch.object(server, "_pip_install", return_value=(False, "offline"))
    @patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=1))
    def test_python_only_failure_is_reported(self, run, pip, changed, user):
        self.assertFalse(self.run_installer()[0])


if __name__ == "__main__":
    unittest.main()
