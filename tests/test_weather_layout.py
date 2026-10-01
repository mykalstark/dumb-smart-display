"""Pixel-level checks for forecast content colliding with the display frame."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.core import theme
from app.display import Display
from app.modules.weather_forecast import Module


class CapturingDriver:
    def render_image(self, image, force_full_refresh=False):
        self.image = image


class WeatherLayoutTests(unittest.TestCase):
    def setUp(self):
        self.module = Module({}, {"default": ImageFont.load_default()})
        self.module._last_fetch = datetime.now()
        start = datetime(2026, 9, 30)  # Wednesday exercises the widest day label.
        self.module._days = [
            {"dt": start + timedelta(days=i),
             "day": (start + timedelta(days=i)).strftime("%a"),
             "icon": ("sun", "sun_cloud", "cloud", "rain", "drizzle", "snow", "storm")[i],
             "high": 120, "low": -40, "precip": 999.99}
            for i in range(7)
        ]

    def test_frame_is_not_thickened_or_crossed_by_content(self):
        for width, height in ((800, 480), (801, 480), (640, 480), (480, 800), (320, 240)):
            for count in (1, 3, 7):
                with self.subTest(size=(width, height), days=count):
                    days = self.module._days
                    self.module._days = days[:count]
                    content = self.module.render(width, height)
                    self.module._days = days
                    driver = CapturingDriver()
                    display = Display(driver=driver)
                    display.render(content)
                    frame = display._add_border(Image.new("1", (width, height), 255))
                    # Entire frame and clearance must match an empty framed image.
                    regions = ((0, 0, theme.OUTER_PAD, height),
                               (width - theme.OUTER_PAD, 0, width, height),
                               (0, 0, width, theme.PAGE_HEADER_RY),
                               (0, height - theme.OUTER_PAD, width, height))
                    for region in regions:
                        diff = ImageChops.difference(driver.image.crop(region), frame.crop(region))
                        self.assertIsNone(diff.getbbox(), region)

    def test_dividers_are_one_pixel_and_stop_inside_the_frame(self):
        image = self.module.render(800, 480)
        for i in range(1, 7):
            x = theme.OUTER_PAD + i * (800 - 2 * theme.OUTER_PAD) // 7
            for y in (theme.PAGE_HEADER_H + theme.OUTER_PAD, 480 - theme.OUTER_PAD - 1):
                self.assertEqual([image.getpixel((x + dx, y)) for dx in (-1, 0, 1)], [255, 0, 255])
            self.assertEqual(image.getpixel((x, 480 - theme.OUTER_PAD)), 255)
        for x in (theme.OUTER_PAD, 800 - theme.OUTER_PAD - 1):
            self.assertEqual(image.getpixel((x, theme.PAGE_HEADER_H)), 0)
            self.assertEqual(image.getpixel((x, theme.PAGE_HEADER_H + 1)), 255)

    def test_visible_text_bounds_fit_their_rows_and_columns(self):
        centered = theme.draw_centered_text
        for width, height in ((800, 480), (320, 240), (480, 800)):
            for fallback in (False, True):
                with self.subTest(size=(width, height), fallback_icons=fallback):
                    def checked_text(draw, box, text, font, fill=0):
                        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
                        self.assertLessEqual(right - left, box[2] - box[0], text)
                        self.assertLessEqual(bottom - top, box[3] - box[1], text)
                        centered(draw, box, text, font, fill)

                    self.module._icon_font_available = False if fallback else None
                    with patch("app.modules.weather_forecast.draw_centered_text", checked_text):
                        self.module.render(width, height)
        # Also cover bearings in the shared centering helper with real pixels.
        font = ImageFont.truetype(theme.HEADER_FONT_PATH, 36)
        image = Image.new("1", (140, 80), 255)
        theme.draw_centered_text(ImageDraw.Draw(image), (10, 10, 130, 70), "WED", font)
        bbox = image.point(lambda value: 255 - value).getbbox()
        self.assertLessEqual(abs((bbox[0] + bbox[2]) - 140), 2)
        self.assertLessEqual(abs((bbox[1] + bbox[3]) - 80), 2)


if __name__ == "__main__":
    unittest.main()
