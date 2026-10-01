"""Offline checks for empty-screen navigation, recovery, and saved options."""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml
from PIL import Image
from werkzeug.datastructures import MultiDict

from app.core.module_manager import ModuleManager
from app.modules import calendar_ics, countdown, mealie_today, rss_feed, spotify_now_playing, ticktick
from app.modules.ticktick_client import TaskItem
from app.webui import server
from app.webui.schema import EMPTY_MODULE_HELP


class FakeModule:
    def __init__(self, name, empty=False):
        self.name = name
        self.empty = empty
        self.ticks = 0
        self.renders = 0

    def is_empty(self):
        return self.empty

    def tick(self):
        self.ticks += 1

    def render(self, width, height):
        self.renders += 1
        return Image.new("1", (width, height), 255)


class NavigationTests(unittest.TestCase):
    def manager(self, modules, settings=None):
        manager = ModuleManager({}, module_config=settings or {})
        manager.modules = modules
        return manager

    def test_opt_in_is_independent_and_defaults_to_visible(self):
        a, b, c = [FakeModule(name, empty=True) for name in ("a", "b", "c")]
        manager = self.manager([a, b, c], {"a": {"hide_when_empty": True}, "b": {"hide_when_empty": False}})
        self.assertIs(manager.current_module(), b)
        self.assertIs(manager.activate_next(), c)
        self.assertIs(manager.activate_next(), b)
        self.assertIs(manager.prev_module(), c)

    def test_buttons_and_iteration_skip_empty_modules_in_both_directions(self):
        a, b, c, d = [FakeModule(name, empty=name in ("b", "d")) for name in "abcd"]
        manager = self.manager([a, b, c, d], {name: {"hide_when_empty": True} for name in "abcd"})
        self.assertIs(manager.current_module(), a)
        self.assertIs(manager.route_button_event("next"), c)
        self.assertIs(manager.route_button_event("next"), a)
        self.assertIs(manager.route_button_event("back"), c)
        self.assertIs(manager.route_button_event("prev"), a)
        # next_module returns the current screen, then advances the cursor.
        self.assertIs(manager.next_module(), a)
        self.assertIs(manager.current_module(), c)
        c.empty = True
        self.assertIs(manager.current_module(), a)

    def test_all_hidden_is_bounded_and_hidden_screens_keep_ticking(self):
        module = FakeModule("a", empty=True)
        manager = self.manager([module], {"a": {"hide_when_empty": True}})
        for select in (manager.current_module, manager.activate_next, manager.next_module, manager.prev_module):
            self.assertIsNone(select())
        manager.tick_modules()
        self.assertEqual(module.ticks, 1)
        module.empty = False
        self.assertIs(manager.current_module(), module)
        self.assertIs(manager.activate_next(), module)
        self.assertIs(manager.prev_module(), module)

    def test_missing_or_broken_empty_hook_stays_visible(self):
        legacy = SimpleNamespace(name="legacy")
        broken = SimpleNamespace(name="broken", is_empty=MagicMock(side_effect=RuntimeError("bad state")))
        manager = self.manager([legacy, broken], {name: {"hide_when_empty": True} for name in ("legacy", "broken")})
        self.assertIs(manager.current_module(), legacy)
        with patch("builtins.print"):
            self.assertIs(manager.activate_next(), broken)

    def test_disabling_every_screen_does_not_discover_and_load_everything(self):
        manager = ModuleManager({}, enabled_modules=[])
        with patch.object(manager, "discover_available_modules") as discover:
            manager.load_modules()
        discover.assert_not_called()
        self.assertEqual(manager.modules, [])
        self.assertIsNone(manager.current_module())

    def test_main_refreshes_before_first_render_and_recovers_from_all_hidden(self):
        from app import main

        module = FakeModule("a")
        manager = self.manager([module], {"a": {"hide_when_empty": True}})

        def tick():
            module.ticks += 1
            module.empty = module.ticks == 1

        module.tick = tick
        display = MagicMock(driver=SimpleNamespace(width=800, height=480), simulate=True)
        args = SimpleNamespace(config="unused.yml", simulate=True, cycles=2)
        with patch.object(main, "parse_args", return_value=args), \
             patch.object(main, "load_config", return_value={"hardware": {"cycle_seconds": 0}}), \
             patch.object(main, "load_fonts", return_value={}), \
             patch.object(main, "build_module_manager", return_value=manager), \
             patch.object(main, "build_display", return_value=display), \
             patch.object(main, "init_buttons"), patch("builtins.print"):
            main.main()
        display.render_text.assert_called_once_with("No content to display.")
        self.assertEqual(module.ticks, 2)
        self.assertEqual(module.renders, 1)
        display.render.assert_called_once()


class EmptyStateTests(unittest.TestCase):
    def test_ticktick_empty_fetch_tomorrow_task_and_error(self):
        module = ticktick.Module({"refresh_seconds": 0}, {})
        self.assertFalse(module.is_empty())
        tomorrow = datetime.now(module.timezone).date() + timedelta(days=1)
        task = TaskItem("Task", "Project", tomorrow, None, True, False)
        with patch.object(module.client, "get_open_tasks_for_range", side_effect=[[], [task], RuntimeError("expired"), []]):
            module.tick()
            self.assertTrue(module.is_empty())
            module.tick()
            self.assertFalse(module.is_empty())
            with self.assertLogs("app.modules.ticktick", level="WARNING"):
                module.tick()
            self.assertFalse(module.is_empty())
            module.tick()
            self.assertTrue(module.is_empty())

    def test_calendar_empty_fetch_tomorrow_event_and_error(self):
        module = calendar_ics.Module({"ics_url": "https://example.invalid/calendar.ics", "refresh_seconds": 0}, {})
        self.assertFalse(module.is_empty())
        event = calendar_ics._Event("Event", date.today() + timedelta(days=1), None, True)
        response = MagicMock(content=b"calendar")
        with patch.object(calendar_ics, "_ICAL_AVAILABLE", True), \
             patch.object(calendar_ics.requests, "get", return_value=response) as get, \
             patch.object(calendar_ics, "_parse_ics", side_effect=[[], [event], []]):
            module.tick()
            self.assertTrue(module.is_empty())
            module.tick()
            self.assertFalse(module.is_empty())
            get.side_effect = RuntimeError("offline")
            with self.assertLogs("app.modules.calendar_ics", level="WARNING"):
                module.tick()
            self.assertFalse(module.is_empty())
            get.side_effect = None
            module.tick()
            self.assertTrue(module.is_empty())

    def test_countdown_uses_visible_date_window(self):
        module = countdown.Module({"show_past_days": 7}, {})
        self.assertTrue(module.is_empty())
        for delta, empty in ((-8, True), (-7, False), (0, False), (365, False)):
            with self.subTest(delta=delta):
                module._events = [{"name": "Event", "date": date.today() + timedelta(days=delta)}]
                self.assertEqual(module.is_empty(), empty)
        module.show_past_days = 0
        module._events = [{"name": "Event", "date": date.today() - timedelta(days=1)}]
        self.assertTrue(module.is_empty())

    def test_mealie_empty_plan_clears_old_dinner_and_recovers(self):
        module = mealie_today.Module({"refresh_seconds": 0}, {})
        self.assertFalse(module.is_empty())
        dinner = [{"entryType": "dinner", "title": "Soup"}]
        lunch = [{"entryType": "lunch", "title": "Sandwich"}]
        with patch.object(module, "_fetch_today_mealplan", side_effect=[dinner, [], None, lunch, dinner]):
            module.force_refresh()
            self.assertFalse(module.is_empty())
            self.assertEqual(module.meal_details["name"], "Soup")
            module.force_refresh()
            self.assertTrue(module.is_empty())
            self.assertNotEqual(module.meal_details["name"], "Soup")
            module.force_refresh()
            self.assertFalse(module.is_empty(), "Fetch failures must remain visible")
            module.force_refresh()
            self.assertTrue(module.is_empty(), "Lunch is not a dinner plan")
            module.force_refresh()
            self.assertFalse(module.is_empty())

    def test_rss_empty_feed_new_headline_and_error(self):
        module = rss_feed.Module({"feed_url": "https://example.invalid/feed", "refresh_seconds": 0}, {})
        self.assertFalse(module.is_empty())
        parsed = SimpleNamespace(bozo=False, feed=SimpleNamespace(title="News"), entries=[])
        with patch.object(rss_feed, "_FEEDPARSER_AVAILABLE", True), \
             patch.object(rss_feed, "feedparser", SimpleNamespace(parse=MagicMock(return_value=parsed)), create=True) as parser:
            module.tick()
            self.assertTrue(module.is_empty())
            parsed.entries = [SimpleNamespace(title="Headline")]
            module.tick()
            self.assertFalse(module.is_empty())
            parser.parse.side_effect = RuntimeError("offline")
            with self.assertLogs("app.modules.rss_feed", level="WARNING"):
                module.tick()
            self.assertFalse(module.is_empty())

    def test_spotify_no_track_paused_track_and_error(self):
        module = spotify_now_playing.Module({"client_id": "id", "client_secret": "secret", "refresh_token": "token", "refresh_seconds": 0}, {})
        self.assertFalse(module.is_empty())
        response = MagicMock(status_code=204)
        with patch.object(module, "_ensure_token"), patch.object(module._session, "get", return_value=response):
            module.tick()
            self.assertTrue(module.is_empty())
            response.status_code = 200
            response.json.return_value = {"item": {"name": "Track"}, "is_playing": False}
            module.tick()
            self.assertFalse(module.is_empty(), "Paused tracks still have content")
            response.json.return_value = {"item": None}
            module.tick()
            self.assertTrue(module.is_empty())
            response.status_code = 401
            module.tick()
            self.assertFalse(module.is_empty(), "Auth errors must remain visible")


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "name" in attrs:
            self.inputs[attrs["name"]] = attrs


class WebSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yml"
        self.path_patch = patch.object(server, "_CONFIG_PATH", self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.restart = patch.object(server, "_restart_service", return_value=(True, "Restarted"))
        self.restart.start()
        self.addCleanup(self.restart.stop)
        self.client = server.app.test_client()

    def test_modules_page_saves_independent_options_preserves_settings_and_order(self):
        server._write_user_config({"modules": {"enabled": ["calendar_ics", "ticktick"], "settings": {
            "ticktick": {"api": {"access_token": "keep"}, "hide_when_empty": True},
            "calendar_ics": {"hide_when_empty": False},
        }}, "hardware": {"cycle_seconds": 42}})
        response = self.client.post("/modules", data=MultiDict([
            ("module_order", "ticktick"), ("module_order", "calendar_ics"),
            ("module_enabled__ticktick", "1"), ("module_enabled__calendar_ics", "1"),
            ("module_hide_when_empty__calendar_ics", "on"),
            ("module_hide_when_empty__countdown", "on"),
        ]))
        self.assertEqual(response.status_code, 302)
        saved = yaml.safe_load(self.path.read_text())
        self.assertEqual(saved["modules"]["enabled"], ["ticktick", "calendar_ics"])
        self.assertEqual(saved["modules"]["settings"]["ticktick"]["api"]["access_token"], "keep")
        self.assertEqual(saved["hardware"]["cycle_seconds"], 42)
        settings = saved["modules"]["settings"]
        for name in EMPTY_MODULE_HELP:
            self.assertEqual(settings[name]["hide_when_empty"], name in ("calendar_ics", "countdown"))
        html = Inputs(self.client.get("/modules").get_data(as_text=True))
        for name in EMPTY_MODULE_HELP:
            attrs = html.inputs[f"module_hide_when_empty__{name}"]
            self.assertEqual(attrs["form"], "modules-form")
            self.assertEqual("checked" in attrs, name in ("calendar_ics", "countdown"))

    @patch.object(server, "_get_current_version", return_value="test")
    def test_config_page_round_trip_includes_all_six_options(self, version):
        response = self.client.post("/config", data={
            "modules__enabled__ticktick": "on",
            "modules__settings__ticktick__hide_when_empty": "on",
            "modules__settings__rss_feed__hide_when_empty": "on",
        })
        self.assertEqual(response.status_code, 302)
        saved = yaml.safe_load(self.path.read_text())
        html = Inputs(self.client.get("/config").get_data(as_text=True))
        for name in EMPTY_MODULE_HELP:
            expected = name in ("ticktick", "rss_feed")
            self.assertEqual(saved["modules"]["settings"][name]["hide_when_empty"], expected)
            self.assertEqual("checked" in html.inputs[f"modules__settings__{name}__hide_when_empty"], expected)


if __name__ == "__main__":
    unittest.main()
