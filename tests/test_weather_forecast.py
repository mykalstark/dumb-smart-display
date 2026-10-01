"""Offline render checks: python -m unittest discover -s tests -v."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from app.core.theme import (
    OUTER_PAD, PAGE_HEADER_H, PAGE_HEADER_RX, PAGE_HEADER_RY, draw_page_header, fit_header_font,
)
from app.modules.weather_forecast import Module, _WMO_GLYPH


class ForecastLayoutTests(unittest.TestCase):
    def make_module(self, count=7, unit="fahrenheit", offset=0, fallback=False):
        module = Module({"temperature_unit": unit}, {"default": ImageFont.load_default()})
        module._last_fetch = datetime.now()  # All checks must stay offline.
        module._icon_font_available = False if fallback else None
        icons = list(_WMO_GLYPH)
        fahrenheit = unit == "fahrenheit"
        highs = [134, -100, 100, 88, None, -108, 104] if fahrenheit else [58, -89, 50, 38, None, -88, 40]
        lows = [-129, -108, -101, -4, None, 88, 68] if fahrenheit else [-94, -90, -89, -20, None, 30, 20]
        module._days = [
            {"dt": datetime(2026, 1, 26) + timedelta(days=i),
             "day": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i],
             "icon": icons[(i + offset) % len(icons)],
             "high": highs[i], "low": lows[i],
             # Near the world daily rainfall record, plus a trace amount.
             "precip": (71.85 if fahrenheit else 1825.0) if i % 2 == 0 else (0.01 if fahrenheit else 0.1)}
            for i in range(count)
        ]
        return module

    def render_with_bounds(self, module, width, height):
        elements = []
        original_text = ImageDraw.ImageDraw.text
        original_paste = Image.Image.paste

        def text(draw, xy, value, *args, **kwargs):
            elements.append((value, draw.textbbox(xy, value, font=kwargs.get("font")),
                             kwargs.get("font")))
            return original_text(draw, xy, value, *args, **kwargs)

        def paste(image, tile, box, *args, **kwargs):
            # Record the complete, measured fallback artwork before pasting,
            # so clipping at a screen edge cannot hide an overflow.
            self.assertIsNotNone(tile.point(lambda p: 255 - p).getbbox())
            elements.append(("fallback icon", (box[0], box[1], box[0] + tile.width,
                                               box[1] + tile.height), None))
            return original_paste(image, tile, box, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", text), patch.object(Image.Image, "paste", paste):
            image = module.render(width, height)
        return image, elements

    def assert_inside(self, box, container):
        self.assertGreaterEqual(box[0], container[0], (box, container))
        self.assertGreaterEqual(box[1], container[1], (box, container))
        self.assertLessEqual(box[2], container[2], (box, container))
        self.assertLessEqual(box[3], container[3], (box, container))

    def test_extremes_stay_in_columns_and_do_not_overlap(self):
        # Include a narrower/portrait canvas, indivisible widths, and every
        # partial forecast size. The two offsets exercise all eight symbols.
        for width, height in [(800, 480), (480, 800), (640, 384), (801, 481)]:
            for count in range(1, 8):
                for unit in ["fahrenheit", "celsius"]:
                    for fallback in [False, True]:
                        for offset in [0, 7]:
                            with self.subTest(size=(width, height), count=count, unit=unit,
                                              fallback=fallback, offset=offset):
                                module = self.make_module(count, unit, offset, fallback)
                                image, elements = self.render_with_bounds(module, width, height)
                                self.assertEqual(image.size, (width, height))
                                self.assertEqual(image.mode, "1")
                                self.assertEqual(len(elements), 1 + count * 6)
                                header_h = min(PAGE_HEADER_H, height // 4)
                                self.assert_inside(elements[0][1],
                                                   (PAGE_HEADER_RX + 8, PAGE_HEADER_RY + 2,
                                                    width - PAGE_HEADER_RX - 8, header_h - PAGE_HEADER_RY - 2))
                                for i in range(count):
                                    column = elements[1 + i * 6:1 + (i + 1) * 6]
                                    body_width = width - 2 * OUTER_PAD
                                    inset = min(8, (body_width // count) // 10)
                                    container = (OUTER_PAD + i * body_width // count + inset,
                                                 header_h + OUTER_PAD,
                                                 OUTER_PAD + (i + 1) * body_width // count - inset,
                                                 height - OUTER_PAD)
                                    for _, box, _ in column:
                                        self.assert_inside(box, container)
                                    boxes = sorted((box for _, box, _ in column), key=lambda b: b[1])
                                    for upper, lower in zip(boxes, boxes[1:]):
                                        self.assertGreaterEqual(lower[1] - upper[3], 6)

    def test_localized_day_labels_are_measured(self):
        module = self.make_module()
        module._days[2]["day"] = "Mié"
        module._days[3]["day"] = "mer."
        _, elements = self.render_with_bounds(module, 480, 800)
        for i in range(7):
            label, box, _ = elements[1 + i * 6]
            self.assertEqual(label, module._days[i]["day"].upper())
            self.assert_inside(box, (OUTER_PAD + i * 440 // 7 + 6, 132,
                                     OUTER_PAD + (i + 1) * 440 // 7 - 6, 780))

    def test_dry_days_omit_precipitation(self):
        module = self.make_module()
        for day in module._days:
            day["precip"] = 0
        _, elements = self.render_with_bounds(module, 800, 480)
        self.assertEqual(len(elements), 1 + 7 * 5)

    def test_error_and_no_data_messages_fit(self):
        module = self.make_module(0)
        for error in [None, "No location configured", "Weather unavailable"]:
            module._error = error
            _, elements = self.render_with_bounds(module, 320, 240)
            self.assertEqual(len(elements), 1)
            self.assert_inside(elements[0][1], (8, 8, 312, 232))

    def test_header_visible_pixels_are_centered_inside_pill(self):
        image = Image.new("1", (800, 480), 255)
        draw = ImageDraw.Draw(image)
        draw_page_header(draw, 800, "7 Day Forecast", fit_header_font(draw, "7 Day Forecast", 800))
        # Check actual white pixels in the rectangular middle of the black pill.
        box = image.crop((50, 16, 750, 96)).getbbox()
        self.assertIsNotNone(box)
        self.assertGreaterEqual(box[1], 2)
        self.assertLessEqual(box[3], 78)
        self.assertLessEqual(abs(box[1] - (80 - box[3])), 1)


if __name__ == "__main__":
    unittest.main()
