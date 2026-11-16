"""Offline integration regressions for external module data."""
import threading
import unittest
from datetime import date, time, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import requests

from app.core.module_manager import ModuleManager
from app.modules import calendar_ics, mealie_today, rss_feed


class RSSFetchTests(unittest.TestCase):
    def setUp(self):
        self.module = rss_feed.Module({"feed_url": "https://example.invalid/feed"}, {})

    def test_fetch_downloads_with_timeouts_then_parses_bytes(self):
        feed = b'''<?xml version="1.0"?><rss version="2.0"><channel>
            <title>Local News</title><link>https://example.invalid/</link>
            <description>News</description><item><title>A headline</title></item>
            </channel></rss>'''
        response = MagicMock(content=feed, headers={"content-type": "application/rss+xml"})
        with patch.object(rss_feed.requests, "get", return_value=response) as get:
            self.module.tick()
            self.module.tick()
        get.assert_called_once_with(self.module.feed_url, timeout=(5, 10))
        response.raise_for_status.assert_called_once()
        self.assertEqual(self.module._feed_title, "Local News")
        self.assertEqual(self.module._items, [{"title": "A headline"}])
        self.assertIsNone(self.module._error)

    def test_http_failure_retains_items_and_throttles_retries(self):
        self.module._items = [{"title": "Cached headline"}]
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("503")
        with patch.object(rss_feed.requests, "get", return_value=response) as get, \
             patch.object(rss_feed.feedparser, "parse") as parse, \
             self.assertLogs("app.modules.rss_feed", level="WARNING"):
            self.module.tick()
            self.module.tick()
        self.assertEqual(get.call_count, 1)
        parse.assert_not_called()
        self.assertEqual(self.module._items, [{"title": "Cached headline"}])
        self.assertFalse(self.module.is_empty())

    def test_malformed_feed_throttles_but_manual_refresh_bypasses_cadence(self):
        response = MagicMock(content=b"not a feed", headers={})
        with patch.object(rss_feed.requests, "get", return_value=response) as get:
            self.module.tick()
            self.module.tick()
            self.assertEqual(get.call_count, 1)
            self.assertIsNotNone(self.module._error)
            self.module.force_refresh()
            self.assertEqual(get.call_count, 2)

    def test_stalled_http_server_does_not_block_other_modules(self):
        release = threading.Event()

        class StalledHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                release.wait(2)

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), StalledHandler) as http:
            worker = threading.Thread(target=http.serve_forever, daemon=True)
            worker.start()
            self.module.feed_url = f"http://127.0.0.1:{http.server_port}/feed"
            following_module = MagicMock()
            manager = ModuleManager({})
            manager.modules = [self.module, following_module]
            try:
                with patch.object(rss_feed, "_REQUEST_TIMEOUT", (0.1, 0.1)), \
                     self.assertLogs("app.modules.rss_feed", level="WARNING"):
                    manager.tick_modules()
                following_module.tick.assert_called_once()
                self.assertEqual(self.module._error, "Feed unavailable")
                self.assertFalse(release.is_set())
            finally:
                release.set()
                http.shutdown()
                worker.join(timeout=2)


class MealieDurationTests(unittest.TestCase):
    def setUp(self):
        self.module = mealie_today.Module({}, {})

    def test_explicit_units_are_never_reinterpreted_as_hours(self):
        for raw, expected in (("PT10M", 10), ("10m", 10), ("10 min", 10),
                              ("PT30S", 1), ("PT1H15M", 75), ("1H 15M", 75),
                              ("PT0M", 0)):
            with self.subTest(raw=raw):
                self.assertEqual(self.module._parse_duration_minutes(
                    raw, assume_hours_if_small=True), expected)

    def test_unitless_legacy_values_keep_existing_behavior(self):
        self.assertEqual(self.module._parse_duration_minutes("2", assume_hours_if_small=True), 120)
        self.assertEqual(self.module._parse_duration_minutes(2, assume_hours_if_small=True), 120)
        self.assertEqual(self.module._parse_duration_minutes("2"), 2)
        self.assertEqual(self.module._parse_duration_minutes("45", assume_hours_if_small=True), 45)

    def test_dinner_with_ten_minute_cook_time_retains_fifteen_minute_total(self):
        details = self.module._extract_dinner_details([{
            "entryType": "dinner", "recipe": {
                "name": "Quick dinner", "prepTime": "PT5M", "cookTime": "PT10M", "totalTime": "PT15M",
            },
        }])
        self.assertEqual(details, {"name": "Quick dinner", "prep": 5, "cook": 10, "total": 15})


class CalendarRecurrenceTests(unittest.TestCase):
    def parse(self, *components, local_timezone=timezone.utc):
        text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Display tests//EN\r\n"
        for component in components:
            text += "BEGIN:VEVENT\r\n" + "\r\n".join(component) + "\r\nEND:VEVENT\r\n"
        text += "END:VCALENDAR\r\n"
        with patch.object(calendar_ics, "tzlocal", return_value=local_timezone):
            events = calendar_ics._parse_ics(text.encode(), (date(2026, 11, 16), date(2026, 11, 17)))
        return sorted(((e.event_date, e.event_time, e.title, e.is_all_day) for e in events),
                      key=lambda event: (event[0], event[1] or time.min, event[2]))

    def weekly(self, *extra):
        return ["UID:weekly", "DTSTART:20261109T100000Z", "SUMMARY:Weekly",
                "RRULE:FREQ=WEEKLY", *extra]

    def test_exdate_removes_excluded_instance(self):
        self.assertEqual(self.parse(self.weekly("EXDATE:20261116T100000Z")), [])

    def test_rdate_adds_an_instance(self):
        events = self.parse(self.weekly("RDATE:20261117T100000Z"))
        self.assertEqual([e[0] for e in events], [date(2026, 11, 16), date(2026, 11, 17)])

    def test_moved_instance_replaces_original(self):
        override = ["UID:weekly", "RECURRENCE-ID:20261116T100000Z",
                    "DTSTART:20261117T140000Z", "SUMMARY:Moved"]
        self.assertEqual(self.parse(self.weekly(), override),
                         [(date(2026, 11, 17), time(14), "Moved", False)])

    def test_moved_instance_outside_window_removes_original(self):
        override = ["UID:weekly", "RECURRENCE-ID:20261116T100000Z",
                    "DTSTART:20261118T140000Z", "SUMMARY:Moved"]
        self.assertEqual(self.parse(self.weekly(), override), [])

    def test_moved_instance_from_outside_window_is_included(self):
        override = ["UID:weekly", "RECURRENCE-ID:20261123T100000Z",
                    "DTSTART:20261117T140000Z", "SUMMARY:Moved"]
        events = self.parse(self.weekly(), override)
        self.assertEqual(events, [(date(2026, 11, 16), time(10), "Weekly", False),
                                  (date(2026, 11, 17), time(14), "Moved", False)])

    def test_cancelled_occurrence_and_series_are_not_displayed(self):
        override = ["UID:weekly", "RECURRENCE-ID:20261116T100000Z",
                    "DTSTART:20261116T100000Z", "STATUS:CANCELLED"]
        self.assertEqual(self.parse(self.weekly(), override), [])
        self.assertEqual(self.parse(self.weekly("STATUS:CANCELLED")), [])
        self.assertEqual(self.parse(["UID:once", "DTSTART:20261116T100000Z", "STATUS:CANCELLED"]), [])

    def test_cancellations_can_omit_start_date(self):
        override = ["UID:weekly", "RECURRENCE-ID:20261116T100000Z", "STATUS:CANCELLED"]
        self.assertEqual(self.parse(self.weekly(), override), [])
        cancellation = ["UID:weekly", "SEQUENCE:1", "STATUS:CANCELLED"]
        self.assertEqual(self.parse(self.weekly("SEQUENCE:0"), cancellation), [])

    def test_incomplete_event_does_not_hide_valid_events(self):
        self.assertEqual(self.parse(self.weekly(), ["UID:incomplete", "SUMMARY:No start"]),
                         [(date(2026, 11, 16), time(10), "Weekly", False)])

    def test_invalid_recurrence_does_not_hide_unrelated_valid_events(self):
        for rule in ("FREQ=INVALID", "FREQ=WEEKLY;BYDAY=XX", "FREQ=DAILY;UNTIL=invalid"):
            with self.subTest(rule=rule):
                malformed = ["UID:malformed", "DTSTART:20261109T100000Z", f"RRULE:{rule}"]
                self.assertEqual(self.parse(self.weekly(), malformed),
                                 [(date(2026, 11, 16), time(10), "Weekly", False)])

    def test_all_day_until_and_exdate_preserve_date_only_semantics(self):
        component = ["UID:allday", "DTSTART;VALUE=DATE:20261101", "SUMMARY:Daily",
                     "RRULE:FREQ=DAILY;UNTIL=20261130"]
        self.assertEqual(self.parse(component, local_timezone=ZoneInfo("America/Denver")),
                         [(date(2026, 11, 16), None, "Daily", True),
                          (date(2026, 11, 17), None, "Daily", True)])
        self.assertEqual(self.parse([*component, "EXDATE;VALUE=DATE:20261116"]),
                         [(date(2026, 11, 17), None, "Daily", True)])

    def test_timed_until_and_local_timezone_conversion(self):
        component = ["UID:night", "DTSTART:20261116T020000Z", "SUMMARY:Evening",
                     "RRULE:FREQ=DAILY;UNTIL=20261118T020000Z"]
        self.assertEqual(self.parse(component, local_timezone=ZoneInfo("America/Denver")),
                         [(date(2026, 11, 16), time(19), "Evening", False),
                          (date(2026, 11, 17), time(19), "Evening", False)])

    def test_nonrecurring_and_floating_events_keep_existing_behavior(self):
        self.assertEqual(self.parse(
            ["UID:float", "DTSTART:20261116T103000", "SUMMARY:Floating"],
            ["UID:date", "DTSTART;VALUE=DATE:20261117", "SUMMARY:All day"],
            ["UID:outside", "DTSTART:20261118T000000Z", "SUMMARY:Outside"],
            local_timezone=ZoneInfo("America/Denver")),
            [(date(2026, 11, 16), time(10, 30), "Floating", False),
             (date(2026, 11, 17), None, "All day", True),
             (date(2026, 11, 17), time(17), "Outside", False)])


if __name__ == "__main__":
    unittest.main()
