"""Cross-screen pixel and text checks using offline data and the real frame."""
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.core import theme
from app.display import Display
from scripts.preview_layouts import CapturingDriver, build_samples, sample_fonts


SIZES = ((800, 480), (801, 481), (640, 384), (480, 800), (320, 240))


class DisplayLayoutTests(unittest.TestCase):
    def capture(self, module, width, height, layout="full"):
        elements = []
        original = ImageDraw.ImageDraw.text

        def text(draw, xy, value, *args, **kwargs):
            bounds = draw.textbbox(xy, value, font=kwargs.get("font"))
            elements.append((str(value), bounds))
            return original(draw, xy, value, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", text):
            content = module.render(width, height, layout=layout)
        return content, elements

    def check_layout(self, module, width, height, layout="full"):
        content, elements = self.capture(module, width, height, layout)
        self.assertEqual(content.mode, "1")
        self.assertEqual(content.size, (width, height))
        self.assertTrue(elements, "The screen must render visible text")
        driver = CapturingDriver()
        display = Display(driver=driver)
        display.render(content)
        frame = display._add_border(Image.new("1", (width, height), 255))
        for region in ((0, 0, theme.OUTER_PAD, height),
                       (width - theme.OUTER_PAD, 0, width, height),
                       (0, 0, width, theme.PAGE_HEADER_RY),
                       (0, height - theme.OUTER_PAD, width, height)):
            self.assertIsNone(ImageChops.difference(driver.image.crop(region), frame.crop(region)).getbbox(), region)
        for text, (x0, y0, x1, y1) in elements:
            self.assertGreaterEqual(x0, theme.OUTER_PAD, text)
            self.assertGreaterEqual(y0, theme.PAGE_HEADER_RY, text)
            self.assertLessEqual(x1, width - theme.OUTER_PAD, text)
            self.assertLessEqual(y1, height - theme.OUTER_PAD, text)
        # Compare measured glyph bounds before canvas clipping can hide errors.
        for i, (text, a) in enumerate(elements):
            for other, b in elements[i + 1:]:
                intersects = max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
                self.assertFalse(intersects, (text, a, other, b))
        return elements

    @patch("requests.sessions.Session.request", side_effect=AssertionError("Layout checks must stay offline"))
    def test_all_screens_states_and_supported_presets(self, request):
        for state in ("normal", "long", "empty", "error"):
            modules = build_samples(state)
            for width, height in SIZES:
                for module in modules:
                    layouts = module.supported_layouts() if module.name in ("clock", "mealie_today") else [None]
                    for preset in layouts:
                        layout = preset.name if preset else "full"
                        with self.subTest(screen=module.name, state=state, size=(width, height), layout=layout):
                            self.check_layout(module, width, height, layout)
        request.assert_not_called()

    def test_compact_screens_keep_key_labels_and_values(self):
        required = {
            "clock": ("Home", "Now", "High", "Low", "72°F", "81°F", "59°F"),
            "mealie_today": ("Prep", "Cook", "Total", "20m", "45m", "1h 5m"),
            "system_status": ("CPU Temp", "CPU Usage", "Memory", "Disk (/)", "Uptime", "IP Address"),
        }
        for module in build_samples():
            if module.name not in required:
                continue
            for preset in module.supported_layouts():
                for width, height in SIZES:
                    with self.subTest(screen=module.name, layout=preset.name, size=(width, height)):
                        _, elements = self.capture(module, width, height, preset.name)
                        texts = [text for text, _ in elements]
                        for label in required[module.name]:
                            self.assertIn(label, texts)
                        if module.name == "clock":
                            self.assertIn(date.today().strftime(module.date_format), texts)

    def test_font_fallback_and_long_unbroken_words(self):
        fonts = dict.fromkeys(("default", "small", "large"), ImageFont.load_default())
        for width, height in ((800, 480), (320, 240)):
            for module in build_samples("long", fonts):
                with self.subTest(screen=module.name, size=(width, height)):
                    self.check_layout(module, width, height)
        image = Image.new("1", (320, 240), 255)
        draw = ImageDraw.Draw(image)
        for text in ("W" * 500, "   ", "jÅé" * 300):
            theme.draw_text_block(draw, (20, 20, 300, 220), text, sample_fonts()["large"], max_lines=3)
        self.assertIsNone(image.crop((0, 0, 20, 240)).point(lambda p: 255 - p).getbbox())

    def test_rss_pagination_matches_capacity_and_resets_on_resize(self):
        module = next(m for m in build_samples() if m.name == "rss_feed")
        _, elements = self.capture(module, 320, 240)
        total = module._total_pages()
        self.assertGreater(total, 1)
        self.assertTrue(any(f"Page 1 / {total}" in text for text, _ in elements))
        module._page = total - 1
        _, elements = self.capture(module, 800, 480)
        self.assertEqual(module._page, 0)
        self.assertFalse(any("Page" in text for text, _ in elements))
        numbers = [int(re.match(r"(\d+)\.", text).group(1)) for text, _ in elements if re.match(r"\d+\.", text)]
        self.assertEqual(numbers, list(range(1, len(module._items) + 1)))

    def test_calendar_and_task_lists_report_hidden_rows(self):
        for name in ("ticktick", "calendar_ics"):
            module = next(m for m in build_samples("long") if m.name == name)
            _, elements = self.capture(module, 800, 480)
            if name == "ticktick":
                total, overflow = len(module.today_tasks), module.today_overflow
                shown = sum(text.startswith("[") and box[0] < 400 for text, box in elements)
            else:
                total, overflow = len(module._today_events), 0
                shown = sum(text[:1].isdigit() and box[0] < 400 for text, box in elements)
            self.assertIn(f"+{total - shown + overflow} more…", [text for text, _ in elements])
            if name == "calendar_ics":
                footer = next(box for text, box in elements if text.startswith("Updated"))
                self.assertGreater(footer[1], max(box[3] for text, box in elements if not text.startswith("Updated")))

    def test_countdown_today_and_past_with_long_names(self):
        module = next(m for m in build_samples("long") if m.name == "countdown")
        for delta in (0, -3, 9999):
            module._events[0]["date"] = date.today() + timedelta(days=delta)
            for width, height in SIZES:
                with self.subTest(delta=delta, size=(width, height)):
                    elements = self.check_layout(module, width, height)
                    self.assertIn("TODAY" if delta == 0 else str(abs(delta)), [text for text, _ in elements])

    def test_spotify_paused_and_system_status_without_ip(self):
        for name in ("spotify_now_playing", "system_status"):
            module = next(m for m in build_samples() if m.name == name)
            if name == "spotify_now_playing":
                module._is_playing = False
            else:
                module.show_ip = False
            for width, height in SIZES:
                elements = self.check_layout(module, width, height)
                texts = [text for text, _ in elements]
                if name == "spotify_now_playing":
                    self.assertIn("Paused", texts)
                else:
                    self.assertNotIn("IP Address", texts)

    def test_startup_and_after_hours_fallback_messages(self):
        from app.main import _render_after_hours

        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                driver = CapturingDriver()
                driver.width, driver.height = width, height
                display = Display(driver=driver)
                elements = []
                original = ImageDraw.ImageDraw.text

                def text(draw, xy, value, *args, **kwargs):
                    elements.append(draw.textbbox(xy, value, font=kwargs.get("font")))
                    return original(draw, xy, value, *args, **kwargs)

                with patch.object(ImageDraw.ImageDraw, "text", text), patch("builtins.print"):
                    display.render_text("Starting display with a very long status message " * 12)
                    _render_after_hours(display, {}, sample_fonts())
                for x0, y0, x1, y1 in elements:
                    self.assertGreaterEqual(x0, theme.OUTER_PAD)
                    self.assertGreaterEqual(y0, theme.OUTER_PAD)
                    self.assertLessEqual(x1, width - theme.OUTER_PAD)
                    self.assertLessEqual(y1, height - theme.OUTER_PAD)
                self.assertEqual(driver.image.size, (width, height))


if __name__ == "__main__":
    unittest.main()
