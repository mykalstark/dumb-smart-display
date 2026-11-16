"""Exercise saved configuration through provider responses to visible content.

HTTP is replaced only at the requests transport boundary. Module fetchers,
provider parsers, manager lifecycle hooks, and renderers all run normally.
These fixtures verify application contracts, not live account connectivity.
"""
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import yaml
from PIL import ImageDraw

from app import main
from app.modules import system_status


MODULE_NAMES = (
    "clock", "weather_forecast", "calendar_ics", "mealie_today", "ticktick",
    "rss_feed", "spotify_now_playing", "countdown", "system_status",
)


class ModulePipelineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_path = Path(directory.name) / "config.yml"
        self.today = date.today()
        self.tomorrow = self.today + timedelta(days=1)
        self.task_today = datetime.now(timezone.utc).date()
        self.calls = []
        self.unexpected_urls = []
        self.weather_failure = False
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.config = {
            "location": {
                "latitude": 40.5, "longitude": -105.25,
                "location_name": "Fixture home", "temperature_unit": "fahrenheit",
                "time_format": "12h",
            },
            "modules": {
                "enabled": list(MODULE_NAMES),
                "settings": {
                    "calendar_ics": {"ics_url": "webcal://fixture.invalid/calendar"},
                    "mealie_today": {"base_url": "https://fixture.invalid/mealie", "api_token": "fixture"},
                    "ticktick": {"api": {"base_url": "https://fixture.invalid/ticktick",
                                           "access_token": "fixture", "timezone": "UTC"}},
                    "rss_feed": {"feed_url": "https://fixture.invalid/feed"},
                    "spotify_now_playing": {"client_id": "fixture", "client_secret": "fixture",
                                            "refresh_token": "fixture"},
                    "countdown": {"events": [{"name": "Launch fixture", "date": self.tomorrow.isoformat()}]},
                },
            },
        }

        def request(session, method, url, **kwargs):
            return self.provider_response(method, url, kwargs)

        self.patches.enter_context(patch("requests.sessions.Session.request", new=request))
        # Fail closed if any request bypasses the fixture transport.
        self.patches.enter_context(patch("requests.sessions.Session.send", side_effect=AssertionError("Unexpected live HTTP")))
        self.patches.enter_context(patch.object(system_status, "_get_cpu_temp", return_value=42))
        self.patches.enter_context(patch.object(system_status, "_get_local_ip", return_value="192.0.2.10"))
        self.cpu = self.patches.enter_context(patch.object(system_status.psutil, "cpu_percent", return_value=12.5))
        self.patches.enter_context(patch.object(system_status.psutil, "virtual_memory",
                                      return_value=SimpleNamespace(used=128 * 1024**2, total=512 * 1024**2, percent=25)))
        self.patches.enter_context(patch.object(system_status.psutil, "disk_usage",
                                      return_value=SimpleNamespace(used=4 * 1024**3, total=16 * 1024**3, percent=25)))
        self.patches.enter_context(patch.object(system_status.psutil, "boot_time",
                                      return_value=datetime.now().timestamp() - 3600))

    def load_manager(self):
        self.config_path.write_text(yaml.safe_dump(self.config), encoding="utf-8")
        with patch("builtins.print"):
            manager = main.build_module_manager(main.load_config(self.config_path), main.load_fonts())
        self.assertEqual([module.name for module in manager.modules], list(MODULE_NAMES))
        return manager, {module.name: module for module in manager.modules}

    def provider_response(self, method, url, kwargs):
        self.calls.append((method.upper(), url, kwargs))
        status = 200
        content_type = "application/json"
        if url == "https://api.open-meteo.com/v1/forecast":
            payload = {
                "current": {"time": self.today.isoformat() + "T12:00", "temperature_2m": 72},
                "daily": {
                    "time": [self.today.isoformat(), self.tomorrow.isoformat()],
                    "weather_code": [0, 3], "temperature_2m_max": [75, 77],
                    "temperature_2m_min": [45, 47], "precipitation_sum": [0, 0.1],
                },
            }
            if self.weather_failure:
                status, payload = 503, {"error": True, "reason": "Provider unavailable"}
        elif url == "https://fixture.invalid/calendar":
            payload = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Display fixture//EN\r\n"
                f"BEGIN:VEVENT\r\nUID:calendar-fixture\r\nDTSTART;VALUE=DATE:{self.today:%Y%m%d}\r\n"
                "RRULE:FREQ=DAILY;COUNT=2\r\nSUMMARY:Meeting fixture\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            ).encode()
            content_type = "text/calendar"
        elif url == "https://fixture.invalid/mealie/api/households/mealplans/today":
            payload = [{"entryType": "dinner", "recipe": {
                "name": "Soup fixture", "prepTime": "PT5M", "performTime": "PT10M", "totalTime": "PT15M",
            }}]
        elif url == "https://fixture.invalid/ticktick/project":
            payload = [{"id": "project-fixture", "name": "Home tasks"}]
        elif url == "https://fixture.invalid/ticktick/project/project-fixture/data":
            payload = {"project": {"id": "project-fixture", "name": "Home tasks"}, "tasks": [
                {"id": "task-fixture", "title": "Task fixture", "isAllDay": False,
                 "dueDate": self.task_today.isoformat() + "T12:00:00+0000", "status": 0},
                {"id": "completed", "title": "Completed fixture", "isAllDay": False,
                 "dueDate": self.task_today.isoformat() + "T10:00:00+0000", "status": 2},
            ]}
        elif url == "https://fixture.invalid/feed":
            payload = b'''<?xml version="1.0"?><rss version="2.0"><channel>
                <title>Local News</title><link>https://fixture.invalid/</link><description>News</description>
                <item><title>Headline fixture</title></item></channel></rss>'''
            content_type = "application/rss+xml"
        elif url == "https://accounts.spotify.com/api/token":
            payload = {"access_token": "fixture-session", "token_type": "Bearer", "expires_in": 3600}
        elif url == "https://api.spotify.com/v1/me/player/currently-playing":
            payload = {"is_playing": True, "item": {
                "name": "Track fixture", "artists": [{"name": "Artist fixture"}],
                "album": {"name": "Album fixture"},
            }}
        else:
            self.unexpected_urls.append(url)
            raise AssertionError("No provider fixture for requested URL")
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.headers["Content-Type"] = content_type
        response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return response

    def assert_provider_data(self, modules, include_weather=True):
        if include_weather:
            self.assertEqual(modules["clock"].weather, {"current": 72, "high": 75, "low": 45})
            self.assertEqual([day["high"] for day in modules["weather_forecast"]._days], [75, 77])
            self.assertIsNone(modules["weather_forecast"]._error)
        calendar = modules["calendar_ics"]
        self.assertIsNone(calendar._error)
        self.assertEqual([event.title for event in calendar._today_events], ["Meeting fixture"])
        self.assertEqual([event.title for event in calendar._tomorrow_events], ["Meeting fixture"])
        self.assertEqual(modules["mealie_today"].meal_details,
                         {"name": "Soup fixture", "prep": 5, "cook": 10, "total": 15})
        self.assertIsNone(modules["ticktick"].error_message)
        self.assertEqual([task.title for task in modules["ticktick"].today_tasks], ["Task fixture"])
        self.assertEqual(modules["ticktick"].today_tasks[0].project_name, "Home tasks")
        self.assertEqual(modules["rss_feed"]._items, [{"title": "Headline fixture"}])
        self.assertIsNone(modules["rss_feed"]._error)
        self.assertEqual(modules["spotify_now_playing"]._track, "Track fixture")
        self.assertEqual(modules["spotify_now_playing"]._artist, "Artist fixture")
        self.assertIsNone(modules["spotify_now_playing"]._error)
        self.assertEqual(modules["countdown"]._visible_events()[0]["name"], "Launch fixture")
        self.assertEqual(modules["system_status"]._stats["cpu_temp"], 42)
        self.assertEqual(modules["system_status"]._stats["ram_pct"], 25)
        self.assertFalse(self.unexpected_urls)

    def test_saved_config_fetches_data_and_renders_each_module(self):
        manager, modules = self.load_manager()
        manager.tick_modules()
        self.assert_provider_data(modules)
        expected_text = {
            "clock": "72", "weather_forecast": "75", "calendar_ics": "Meeting fixture",
            "mealie_today": "Soup fixture", "ticktick": "Task fixture", "rss_feed": "Headline fixture",
            "spotify_now_playing": "Track fixture", "countdown": "Launch fixture", "system_status": "42",
        }
        original_text = ImageDraw.ImageDraw.text
        for name, module in modules.items():
            with self.subTest(module=name):
                text = []

                def capture(draw, xy, value, *args, **kwargs):
                    text.append(str(value))
                    return original_text(draw, xy, value, *args, **kwargs)

                with patch.object(ImageDraw.ImageDraw, "text", new=capture):
                    image = module.render(width=800, height=480)
                self.assertEqual(image.size, (800, 480))
                self.assertEqual(image.mode, "1")
                self.assertTrue(any(expected_text[name] in value for value in text), text)

    def test_shared_location_and_provider_credentials_reach_http_boundary(self):
        self.config["modules"]["settings"]["weather_forecast"] = {"latitude": 41.5}
        manager, modules = self.load_manager()
        manager.tick_modules()
        weather = [kwargs for _, url, kwargs in self.calls if url.endswith("/forecast")]
        self.assertEqual(len(weather), 2)
        self.assertEqual(weather[0]["params"]["latitude"], 40.5)
        self.assertEqual(weather[1]["params"]["latitude"], 41.5)
        for kwargs in weather:
            self.assertEqual(kwargs["params"]["longitude"], -105.25)
            self.assertEqual(kwargs["params"]["temperature_unit"], "fahrenheit")
        for name in ("clock", "ticktick", "calendar_ics", "rss_feed", "spotify_now_playing"):
            self.assertEqual(modules[name].time_format, "%I:%M %p")
        by_url = {url: (method, kwargs) for method, url, kwargs in self.calls}
        for url in ("https://fixture.invalid/mealie/api/households/mealplans/today",
                    "https://fixture.invalid/ticktick/project"):
            self.assertEqual(by_url[url][1]["headers"]["Authorization"], "Bearer fixture")
        token_method, token_kwargs = by_url["https://accounts.spotify.com/api/token"]
        self.assertEqual(token_method, "POST")
        self.assertEqual(token_kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(token_kwargs["data"]["refresh_token"], "fixture")
        self.assertEqual(by_url["https://api.spotify.com/v1/me/player/currently-playing"][1]["headers"]["Authorization"],
                         "Bearer fixture-session")
        self.assertTrue(all(kwargs.get("timeout") for _, _, kwargs in self.calls))

    def test_polling_is_throttled_and_manager_refresh_fetches_current_data(self):
        manager, modules = self.load_manager()
        manager.tick_modules()
        initial_requests = len(self.calls)
        initial_stats = self.cpu.call_count
        manager.tick_modules()
        self.assertEqual(len(self.calls), initial_requests)
        self.assertEqual(self.cpu.call_count, initial_stats)
        for index, module in enumerate(manager.modules):
            with self.subTest(module=module.name):
                manager._active_index = index
                previous_requests = len(self.calls)
                manager.route_button_event("refresh")
                if module.name not in {"countdown", "system_status"}:
                    self.assertGreater(len(self.calls), previous_requests)
        self.assertEqual(self.cpu.call_count, initial_stats + 1)
        self.assertEqual(sum(url.endswith("/api/token") for _, url, _ in self.calls), 1)
        self.assert_provider_data(modules)

    def test_weather_outage_does_not_block_other_modules_and_refresh_recovers(self):
        manager, modules = self.load_manager()
        self.weather_failure = True
        with self.assertLogs(level="WARNING"):
            manager.tick_modules()
        self.assertEqual(modules["weather_forecast"]._error, "Weather unavailable")
        self.assert_provider_data(modules, include_weather=False)
        self.weather_failure = False
        for name in ("clock", "weather_forecast"):
            manager._active_index = list(MODULE_NAMES).index(name)
            manager.route_button_event("refresh")
        self.assert_provider_data(modules)


if __name__ == "__main__":
    unittest.main()
