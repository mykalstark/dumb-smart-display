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
    def test_header_bar_and_text_are_centered_in_the_framed_header_box(self):
        display = Display(driver=CapturingDriver())
        titles = ("Home", "Now Playing", "Tonight's Dinner", "Good News", "Family Vacation", "7 Day Forecast")
        for width, height in SIZES:
            header_h = min(theme.PAGE_HEADER_H, height // 4)
            blank = Image.new("1", (width, height), 255)
            frame = display._add_border(blank)
            # Measure the visible interior from the actual display frame.
            frame_top = max(y for y in range(theme.OUTER_PAD) if frame.getpixel((width // 2, y)) == 0) + 1
            header = blank.copy()
            theme.draw_page_header(ImageDraw.Draw(header), width, "", sample_fonts()["default"], header_h)
            bar = header.crop((0, 0, width, header_h)).point(lambda p: 255 - p).getbbox()
            self.assertIsNotNone(bar)
            self.assertGreater(bar[1] - frame_top, 0)
            self.assertLessEqual(abs((bar[1] - frame_top) - (header_h - bar[3])), 1)
            self.assertLessEqual(abs(bar[0] - (width - bar[2])), 1)
            for title in titles:
                with self.subTest(size=(width, height), title=title):
                    image = blank.copy()
                    theme.draw_page_header(ImageDraw.Draw(image), width, title,
                                           theme.fit_header_font(ImageDraw.Draw(image), title, width, header_h), header_h)
                    # Subtract the empty pill to isolate all title pixels,
                    # including wide text extending into the rounded ends.
                    text = ImageChops.difference(image, header).crop(bar).getbbox()
                    self.assertIsNotNone(text)
                    text_h = bar[3] - bar[1]
                    text_w = bar[2] - bar[0]
                    self.assertLessEqual(abs(text[1] - (text_h - text[3])), 1)
                    # Font bounding boxes can include unpainted edge pixels;
                    # allow up to 1.5 px of horizontal raster asymmetry.
                    self.assertLessEqual(abs(text[0] - (text_w - text[2])), 3)

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

    def test_rss_preserves_full_wrapped_titles(self):
        title = ("Local library opens a new reading room with free activities for families "
                 "and a community garden where neighbors can share books and learn together")
        for width, height in ((800, 480), (640, 384), (480, 800)):
            module = next(m for m in build_samples() if m.name == "rss_feed")
            module._items = [{"title": title}]
            with self.subTest(size=(width, height)):
                elements = self.check_layout(module, width, height)
                lines = [text for text, box in elements
                         if box[1] >= min(theme.PAGE_HEADER_H, height // 4) + theme.OUTER_PAD
                         and not text.startswith("Updated")]
                self.assertGreater(len(lines), 1)
                self.assertEqual(" ".join(lines), f"1. {title}")
                self.assertEqual(module._total_pages(), 1)

    def test_rss_pages_variable_height_articles_without_skips(self):
        title = ("Local library opens a new reading room with free activities for families "
                 "and a community garden where neighbors can share books and learn together")
        titles = ["Brief local update", "Quick community news", title,
                  "Town festival announced", title, "Weekend market opens"]
        module = next(m for m in build_samples() if m.name == "rss_feed")
        module._items = [{"title": title} for title in titles]
        self.capture(module, 640, 384)
        total_pages = module._total_pages()
        self.assertGreater(total_pages, 1)
        article_lines = []
        for page in range(total_pages):
            self.assertEqual(module._page, page)
            elements = self.check_layout(module, 640, 384)
            article_lines.extend(text for text, box in elements
                                 if box[1] >= min(theme.PAGE_HEADER_H, 384 // 4) + theme.OUTER_PAD
                                 and not text.startswith("Page"))
            self.assertTrue(any(f"Page {page + 1} / {total_pages}" in text for text, _ in elements))
            module.handle_button("next")
        self.assertEqual(" ".join(article_lines),
                         " ".join(f"{i + 1}. {title}" for i, title in enumerate(titles)))
        self.assertEqual(module._page, 0)
        module.handle_button("back")
        self.assertEqual(module._page, total_pages - 1)
        module.handle_button("prev")
        self.assertEqual(module._page, (total_pages - 2) % total_pages)

    def test_rss_oversized_title_stops_above_footer_and_next_article_is_reachable(self):
        for width, height in ((800, 480), (320, 240)):
            module = next(m for m in build_samples() if m.name == "rss_feed")
            module._items = [{"title": "An exceptionally long headline with café details " * 100},
                             {"title": "Next article"}]
            with self.subTest(size=(width, height)):
                elements = self.check_layout(module, width, height)
                lines = [(text, box) for text, box in elements
                         if box[1] >= min(theme.PAGE_HEADER_H, height // 4) + theme.OUTER_PAD
                         and not text.startswith("Page")]
                self.assertGreater(len(lines), 1)
                self.assertTrue(lines[-1][0].endswith("…"))
                footer = next(box for text, box in elements if text.startswith("Page"))
                self.assertLess(lines[-1][1][3], footer[1])
                self.assertEqual(module._total_pages(), 2)
                module.handle_button("next")
                elements = self.check_layout(module, width, height)
                self.assertIn("2. Next article", [text for text, _ in elements])

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
