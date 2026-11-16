"""Settings saves must remain usable by the runtime and preserve custom screens."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

from app.webui import server


class ConfigSaveTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.yml"
        for name, value in {
            "_CONFIG_PATH": self.path,
            "_get_current_version": lambda: "test-version",
        }.items():
            replacement = patch.object(server, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        restart = patch.object(server, "_restart_service", return_value=(True, "Restarted"))
        self.restart = restart.start()
        self.addCleanup(restart.stop)
        self.client = server.app.test_client()
        server._write_user_config({
            "modules": {"enabled": ["clock"], "settings": {"clock": {"refresh_seconds": 1800}}},
            "hardware": {"cycle_seconds": 30},
            "webui": {"port": 8080, "password": ""},
        })

    def assert_rejected(self, field, value, message):
        original = self.path.read_bytes()
        response = self.client.post("/config", data={field: value})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.path.read_bytes(), original)
        self.restart.assert_not_called()
        with self.client.session_transaction() as session:
            self.assertIn(message, session["_flashes"][-1][1])


class ConfigValidationTests(ConfigSaveTestCase):
    def test_blank_invalid_and_nonfinite_numbers_never_reach_config(self):
        fields = [
            ("hardware__cycle_seconds", "Module Cycle Interval"),
            ("hardware__spi_hz", "SPI Clock"),
            ("webui__port", "Port"),
            ("modules__settings__clock__refresh_seconds", "Weather Refresh Interval"),
            ("location__latitude", "Latitude"),
        ]
        for field, label in fields:
            for value in ("", " ", "not a number", "NaN", "inf", "-Infinity", "1e309"):
                with self.subTest(field=field, value=value):
                    self.assert_rejected(field, value, label)

    def test_fractional_counts_and_intervals_are_rejected(self):
        for field, value in (
            ("hardware__cycle_seconds", "30.5"),
            ("hardware__spi_hz", "4000000.5"),
            ("webui__port", "8080.5"),
            ("modules__settings__clock__time_size", "120.5"),
            ("modules__settings__countdown__show_past_days", "1.5"),
        ):
            with self.subTest(field=field):
                self.assert_rejected(field, value, "whole number")

    def test_schema_bounds_apply_without_browser_validation(self):
        for field, value, message in (
            ("hardware__cycle_seconds", "4", "at least 5"),
            ("hardware__cycle_seconds", "1e20", "at most"),
            ("hardware__spi_hz", "99999", "at least 100000"),
            ("webui__port", "65536", "at most 65535"),
            ("webui__port", "1023", "at least 1024"),
            ("location__latitude", "90.1", "at most 90"),
            ("location__longitude", "-180.1", "at least -180"),
            ("modules__settings__clock__time_size", "201", "at most 200"),
            ("modules__settings__countdown__show_past_days", "-1", "at least 0"),
        ):
            with self.subTest(field=field, value=value):
                self.assert_rejected(field, value, message)

    def test_valid_numbers_and_partial_forms_preserve_existing_values(self):
        response = self.client.post("/config", data={
            "modules__enabled__clock": "on",
            "location__latitude": "40.513217",
            "location__longitude": "-112.321445",
            "hardware__cycle_seconds": "45.0",
            "webui__port": "8081",
            "modules__settings__countdown__show_past_days": "0",
            # Disabled credentials remain optional.
            "modules__settings__mealie_today__api_token": "",
        })
        self.assertEqual(response.status_code, 302)
        saved = server._load_user_config()
        self.assertEqual(saved["location"]["latitude"], 40.513217)
        self.assertEqual(saved["location"]["longitude"], -112.321445)
        self.assertEqual(saved["hardware"]["cycle_seconds"], 45)
        self.assertIsInstance(saved["hardware"]["cycle_seconds"], int)
        self.assertEqual(saved["webui"]["port"], 8081)
        self.assertEqual(saved["modules"]["settings"]["clock"]["refresh_seconds"], 1800)
        self.assertEqual(saved["modules"]["settings"]["countdown"]["show_past_days"], 0)
        self.restart.assert_called_once()


class CustomModuleSaveTests(ConfigSaveTestCase):
    def setUp(self):
        super().setUp()
        server._write_user_config({
            "modules": {
                "enabled": ["custom_first", "countdown", "custom_middle", "clock", "custom_last"],
                "settings": {"custom_middle": {"api_token": "retained", "hide_when_empty": True}},
            },
        })

    def test_settings_save_preserves_custom_order_and_settings(self):
        self.client.post("/config", data={
            "location__location_name": "Studio",
            "modules__enabled__clock": "on",
            "modules__enabled__countdown": "on",
            "modules__enabled__system_status": "on",
        })
        saved = server._load_user_config()
        self.assertEqual(saved["modules"]["enabled"], [
            "custom_first", "countdown", "custom_middle", "clock", "custom_last", "system_status",
        ])
        self.assertEqual(saved["modules"]["settings"]["custom_middle"], {
            "api_token": "retained", "hide_when_empty": True,
        })

    def test_module_order_save_preserves_unrendered_custom_slots(self):
        self.assertEqual(self.client.get("/modules").status_code, 200)
        self.client.post("/modules", data=MultiDict([
            ("module_order", "clock"), ("module_order", "countdown"),
            ("module_order", "clock"),
            ("module_enabled__clock", "on"), ("module_enabled__countdown", "on"),
        ]))
        saved = server._load_user_config()
        self.assertEqual(saved["modules"]["enabled"], [
            "custom_first", "clock", "custom_middle", "countdown", "custom_last",
        ])
        self.assertEqual(saved["modules"]["settings"]["custom_middle"]["api_token"], "retained")

    def test_disabling_builtins_does_not_disable_unrendered_modules(self):
        for endpoint in ("/config", "/modules"):
            with self.subTest(endpoint=endpoint):
                self.client.post(endpoint, data={})
                self.assertEqual(server._load_user_config()["modules"]["enabled"], [
                    "custom_first", "custom_middle", "custom_last",
                ])

    def test_unknown_submitted_names_do_not_enable_new_modules(self):
        self.client.post("/modules", data=MultiDict([
            ("module_order", "not_configured"), ("module_enabled__not_configured", "on"),
        ]))
        self.assertNotIn("not_configured", server._load_user_config()["modules"]["enabled"])

    def test_custom_modules_from_defaults_are_preserved(self):
        server._write_user_config({})
        with patch.object(server, "_load_example_config", return_value={
            "modules": {"enabled": ["custom_default", "clock"]},
        }):
            self.client.post("/config", data={"modules__enabled__clock": "on"})
        self.assertEqual(server._load_user_config()["modules"]["enabled"], ["custom_default", "clock"])


if __name__ == "__main__":
    unittest.main()
