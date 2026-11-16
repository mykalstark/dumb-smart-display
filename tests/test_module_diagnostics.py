"""Diagnostics distinguish setup/network failures without exposing private data."""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from unittest.mock import patch

import requests

from app.modules import calendar_ics
from scripts.check_modules import check_module


class ModuleDiagnosticsTests(unittest.TestCase):
    def test_unset_weather_coordinates_do_not_make_requests(self):
        with patch("requests.sessions.Session.request") as request:
            state, detail = check_module({"location": {"latitude": None, "longitude": None}}, "clock", {})
        self.assertEqual(state, "SETUP")
        self.assertIn("coordinates", detail)
        request.assert_not_called()

    def test_missing_calendar_dependency_is_distinct_from_network_error(self):
        config = {"modules": {"settings": {"calendar_ics": {"ics_url": "https://private.invalid/SECRET"}}}}
        with patch.object(calendar_ics, "_ICAL_AVAILABLE", False), \
             patch("requests.sessions.Session.request") as request:
            state, detail = check_module(config, "calendar_ics", {})
        self.assertEqual(state, "SETUP")
        self.assertIn("dependencies", detail)
        request.assert_not_called()

    def test_private_url_is_not_disclosed_on_network_failure(self):
        secret = "https://private.invalid/SECRET-CALENDAR-TOKEN"
        config = {"modules": {"settings": {"calendar_ics": {"ics_url": secret}}}}
        output = io.StringIO()
        with patch("requests.sessions.Session.request", side_effect=requests.exceptions.ProxyError(secret)), \
             redirect_stdout(output), redirect_stderr(output):
            result = check_module(config, "calendar_ics", {})
        self.assertEqual(result[0], "ERROR")
        self.assertIn("ProxyError", result[1])
        self.assertNotIn("SECRET-CALENDAR-TOKEN", output.getvalue() + str(result))

    def test_successful_calendar_does_not_disclose_event_content(self):
        secret = "PRIVATE-EVENT-TITLE"
        response = requests.Response()
        response.status_code = 200
        response._content = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1\r\n"
                             f"DTSTART;VALUE=DATE:{date.today():%Y%m%d}\r\nSUMMARY:{secret}\r\n"
                             "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()
        config = {"modules": {"settings": {"calendar_ics": {"ics_url": "https://private.invalid/calendar"}}}}
        output = io.StringIO()
        with patch("requests.sessions.Session.request", return_value=response), \
             redirect_stdout(output), redirect_stderr(output):
            result = check_module(config, "calendar_ics", {})
        self.assertEqual(result[0], "OK")
        self.assertNotIn(secret, output.getvalue() + str(result))


if __name__ == "__main__":
    unittest.main()
