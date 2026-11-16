"""Run the installer against fake privilege/system tools and a temporary checkout."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAKE_TOOL = r'''
import json, os, pathlib, shutil, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
user = os.environ.get("FAKE_USER", "root")
with open(os.environ["INSTALL_LOG"], "a") as log:
    log.write(json.dumps([name, user, args]) + "\n")
if name == "id":
    target = args[-1] if args[-1] not in ("-u", "-un") else user
    print(target if args[0] == "-un" else "0" if target == "root" else "1001")
elif name == "systemctl":
    if args[0] == "show": print(os.environ.get("SERVICE_USER", "displayuser"))
elif name == "hostname":
    print("127.0.0.1")
elif name == "git":
    if args == ["rev-parse", "HEAD"]: print("after")
elif name == "sudo":
    env = dict(os.environ)
    while args and args[0].startswith("-"):
        flag = args.pop(0)
        if flag == "--": break
        if flag == "-u": env["FAKE_USER"] = args.pop(0)
    if args[0] in ("mv", "chmod", "tee") and args[-1].startswith("/etc/"):
        target = pathlib.Path(os.environ["SYSTEM_ROOT"]) / args[-1].lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if args[0] == "mv": shutil.move(args[-2], target)
        elif args[0] == "tee": target.write_text(sys.stdin.read())
    else:
        sys.exit(subprocess.call(args, env=env))
elif name in ("python", "python3"):
    if args[:2] != ["-m", "pip"]:
        raise SystemExit("Unexpected Python invocation: " + repr(args))
elif name not in ("apt", "pip3", "raspi-config"):
    raise SystemExit("Unexpected command: " + name)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app = self.root / "app"
        self.app.mkdir()
        shutil.copytree(ROOT / "systemd", self.app / "systemd")
        library = self.app / "lib" / "waveshare_epd"
        library.mkdir(parents=True)
        (library / "epdconfig.py").write_text("RST_PIN = 17\n")
        venv = self.app / ".venv" / "bin"
        venv.mkdir(parents=True)
        binaries = self.root / "bin"
        binaries.mkdir()
        script = "#!" + sys.executable + "\n" + FAKE_TOOL
        for command in ("id", "sudo", "apt", "systemctl", "pip3", "raspi-config", "hostname", "git"):
            target = binaries / command
            target.write_text(script)
            target.chmod(0o755)
        (venv / "python").write_text(script)
        (venv / "python").chmod(0o755)
        self.log = self.root / "commands.jsonl"
        self.env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                    "APP_DIR": str(self.app), "INSTALL_LOG": str(self.log),
                    "SYSTEM_ROOT": str(self.root / "system"), "FAKE_USER": "root",
                    "SUDO_USER": "caller", "SERVICE_USER": "displayuser"}
        self.env.pop("APP_USER", None)

    def run_install(self, *args):
        return subprocess.run(["bash", str(ROOT / "scripts" / "install.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_account(self, expected):
        for unit in ("dumb-smart-display", "dumb-smart-display-webui"):
            text = (self.root / "system" / "etc" / "systemd" / "system" / (unit + ".service")).read_text()
            self.assertIn("User=" + expected + "\n", text)
        rules = (self.root / "system" / "etc" / "sudoers.d" / "dumb-smart-display-restart").read_text()
        self.assertTrue(rules.startswith(expected + " ALL="))
        pip_commands = [(user, args) for name, user, args in self.commands() if name == "python"]
        self.assertEqual(len(pip_commands), 2)
        self.assertTrue(all(user == expected for user, _ in pip_commands))
        self.assertEqual((self.app / "lib" / "waveshare_epd" / "epdconfig.py").read_text(), "RST_PIN = 5\n")
        self.assertEqual((self.app / "config" / ".system-install-revision").read_text(), "after\n")

    def test_sudo_install_preserves_deployed_user_and_project_mutation_identity(self):
        result = self.run_install("--update")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_account("displayuser")
        commands = self.commands()
        self.assertFalse(any(name == "systemctl" and args[0] == "start" for name, _, args in commands))
        for executable in ("mkdir", "sed", "tee"):
            self.assertTrue(any(name == "sudo" and args[:4] == ["-H", "-u", "displayuser", "--"]
                                and args[4] == executable for name, _, args in commands))

    def test_explicit_app_user_remains_supported(self):
        result = self.run_install("--update", "--app-user", "customuser")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_account("customuser")

    def test_normal_unprivileged_install_preserves_account_and_starts_services(self):
        self.env["FAKE_USER"] = "localuser"
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_account("localuser")
        starts = [args for name, _, args in self.commands() if name == "systemctl" and args[0] == "start"]
        self.assertEqual(len(starts), 2)

    def test_root_without_application_account_stops_before_system_changes(self):
        self.env["SERVICE_USER"] = ""
        self.env["SUDO_USER"] = "root"
        result = self.run_install("--update")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-root", result.stderr)
        self.assertFalse(any(name == "apt" for name, _, _ in self.commands()))


if __name__ == "__main__":
    unittest.main()
