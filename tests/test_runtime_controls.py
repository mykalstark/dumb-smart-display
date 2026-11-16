"""Exercise button gestures through routing and real module state."""
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app import buttons, main
from app.core.module_manager import ModuleManager
from app.display import Display
from app.modules import countdown, rss_feed, spotify_now_playing, system_status, ticktick, weather_forecast


class FakeButton:
    instances = []

    def __init__(self, pin, **kwargs):
        self.pin = pin
        self.options = kwargs
        self.when_pressed = self.when_released = self.when_held = None
        self.instances.append(self)

    def tap(self):
        self.when_pressed()
        if self.when_released:
            self.when_released()

    def hold(self):
        self.when_pressed()
        self.when_held()
        self.when_released()


class RuntimeControlTests(unittest.TestCase):
    def manager(self, *modules):
        manager = ModuleManager({})
        manager.modules = list(modules)
        return manager

    def wire_buttons(self, callback):
        FakeButton.instances = []
        with patch.object(buttons, '_import_button', return_value=FakeButton), \
             patch.dict(buttons.os.environ, {'DISPLAY_SIMULATE': ''}), \
             patch('builtins.print'):
            buttons.init_buttons(on_event=callback)
        self.addCleanup(setattr, buttons, '_BUTTONS', [])
        return FakeButton.instances

    def test_taps_wait_for_release_and_hold_never_dispatches_a_tap(self):
        events = []
        left, middle, right = self.wire_buttons(events.append)
        right.when_pressed()
        self.assertEqual(events, [])
        right.when_released()
        left.hold()
        right.hold()
        left.tap()
        middle.tap()
        self.assertEqual(events, ['next', 'module_back', 'module_next', 'back', 'refresh'])
        self.assertEqual(right.options['hold_time'], 1.0)

    def test_gpio_taps_page_rss_and_holds_switch_modules(self):
        rss = rss_feed.Module({}, {})
        rss._items = [{'title': 'First'}, {'title': 'Second'}]
        rss._page_starts = [0, 1]
        other = SimpleNamespace(name='other')
        manager = self.manager(rss, other)
        left, _, right = self.wire_buttons(manager.route_button_event)
        right.tap()
        self.assertIs(manager.current_module(), rss)
        self.assertEqual(rss._page, 1)
        left.tap()
        self.assertEqual(rss._page, 0)
        right.hold()
        self.assertIs(manager.current_module(), other)
        self.assertEqual(rss._page, 0)
        left.hold()
        self.assertIs(manager.current_module(), rss)
        self.assertEqual(rss._page, 0)

    def test_countdown_taps_cycle_events_and_automatic_cycle_still_advances(self):
        events = [{'name': name, 'date': (date.today() + timedelta(days=n)).isoformat()}
                  for n, name in enumerate(['First', 'Second'])]
        module = countdown.Module({'events': events}, {})
        other = SimpleNamespace(name='other')
        manager = self.manager(module, other)
        manager.route_button_event('next')
        self.assertEqual(module._active_index, 1)
        self.assertIs(manager.current_module(), module)
        manager.route_button_event('prev')
        self.assertEqual(module._active_index, 0)
        self.assertIs(manager.activate_next(), other)

    def test_single_page_and_legacy_modules_use_normal_navigation(self):
        rss = rss_feed.Module({}, {})
        rss._items = [{'title': 'Only headline'}]
        legacy = SimpleNamespace(name='legacy', handle_button=MagicMock(), tick=MagicMock())
        manager = self.manager(rss, legacy)
        self.assertIs(manager.route_button_event('next'), legacy)
        self.assertIs(manager.route_button_event('back'), rss)
        legacy.handle_button.assert_not_called()

    def test_hold_navigation_skips_hidden_modules(self):
        first = SimpleNamespace(name='first')
        hidden = SimpleNamespace(name='hidden', is_empty=lambda: True)
        last = SimpleNamespace(name='last')
        manager = self.manager(first, hidden, last)
        manager.module_config = {'hidden': {'hide_when_empty': True}}
        self.assertIs(manager.route_button_event('module_next'), last)
        self.assertIs(manager.route_button_event('module_back'), first)

    def test_refresh_bypasses_rss_throttle_and_keeps_legacy_tick(self):
        rss = rss_feed.Module({'refresh_seconds': 1800}, {})
        rss._last_fetch = datetime.now()
        rss._page = 1
        manager = self.manager(rss)
        with patch.object(rss, '_fetch') as fetch:
            manager.route_button_event('refresh')
        fetch.assert_called_once()
        self.assertEqual(rss._page, 0)
        legacy = SimpleNamespace(name='legacy', handle_button=MagicMock(), tick=MagicMock())
        manager.modules = [legacy]
        manager.route_button_event('refresh')
        legacy.handle_button.assert_called_once_with('refresh')
        legacy.tick.assert_called_once()

    def test_builtin_refresh_bypasses_throttle(self):
        for module, fetch_name in (
            (weather_forecast.Module({}, {}), '_fetch'),
            (spotify_now_playing.Module({}, {}), '_fetch_now_playing'),
            (system_status.Module({}, {}), '_collect_stats'),
        ):
            with self.subTest(module=module.name), patch.object(module, fetch_name) as fetch:
                module._last_fetch = datetime.now()
                self.manager(module).route_button_event('refresh')
                fetch.assert_called_once()
        tasks = ticktick.Module({}, {})
        tasks.last_fetch = datetime.now(tasks.timezone)
        with patch.object(tasks.client, 'get_open_tasks_for_range', return_value=[]) as fetch:
            self.manager(tasks).route_button_event('refresh')
        fetch.assert_called_once()

    def test_main_renders_modules_in_logical_portrait_dimensions(self):
        module = SimpleNamespace(name='probe', tick=MagicMock(),
                                 render=MagicMock(return_value=Image.new('1', (480, 800))))
        driver = SimpleNamespace(width=800, height=480, render_image=MagicMock())
        display = Display(driver=driver, rotation=90)
        args = SimpleNamespace(config='unused.yml', simulate=True, cycles=1)
        with patch.object(main, 'parse_args', return_value=args), \
             patch.object(main, 'load_config', return_value={}), \
             patch.object(main, 'load_fonts', return_value={}), \
             patch.object(main, 'build_module_manager', return_value=self.manager(module)), \
             patch.object(main, 'build_display', return_value=display), \
             patch.object(main, 'init_buttons'), patch('builtins.print'):
            main.main()
        module.render.assert_called_once_with(width=480, height=800)

    def test_after_hours_prepares_photo_at_logical_portrait_size(self):
        display = Display(driver=SimpleNamespace(width=800, height=480), rotation=270)
        config = {'hardware': {'after_hours': {'photo': 'example.jpg'}}}
        with patch.object(main, '_prepare_after_hours_source', return_value=Image.new('L', (480, 800), 255)) as source, \
             patch.object(main, '_select_best_monochrome_variant',
                          return_value=(Image.new('1', (480, 800)), 0.5, 1.0)), \
             patch.object(display, 'render_photo', return_value='1bit_floyd') as render, \
             patch('builtins.print'):
            main._render_after_hours(display, config, {})
        self.assertEqual(source.call_args.args[1:3], (480, 800))
        self.assertEqual(render.call_args.args[0].size, (480, 800))


if __name__ == '__main__':
    unittest.main()
