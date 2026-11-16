"""Exercise logical portrait canvases through the physical panel pipelines."""
import unittest
from unittest.mock import patch

from PIL import Image

from app.display import Display, HardwareDisplayDriver, SimulatorDisplayDriver


class Panel:
    width = 800
    height = 480

    def init(self):
        pass

    init_4Gray = init
    sleep = init

    def getbuffer(self, image):
        return image.copy()

    getbuffer_4Gray = getbuffer

    def display(self, image):
        self.image = image

    display_4Gray = display


def hardware(rotation):
    """Use the real render methods without opening GPIO or SPI devices."""
    driver = HardwareDisplayDriver.__new__(HardwareDisplayDriver)
    driver.driver = Panel()
    driver.width, driver.height = 800, 480
    driver.rotation = rotation
    driver.spi_hz = None
    driver._refresh_counter = 0
    driver._full_refresh_rate = 10
    driver._fast_display = None
    return driver


def panel_point(point, size, rotation):
    x, y = point
    width, height = size
    return {
        0: (x, y),
        90: (y, width - 1 - x),
        180: (width - 1 - x, height - 1 - y),
        270: (height - 1 - y, x),
    }[rotation]


class DisplayRotationTests(unittest.TestCase):
    def test_logical_dimensions_follow_rotation_for_hardware_and_simulator(self):
        for rotation in (0, 90, 180, 270):
            expected = (480, 800) if rotation in (90, 270) else (800, 480)
            for driver in (hardware(rotation), SimulatorDisplayDriver(rotation=rotation)):
                with self.subTest(rotation=rotation, driver=type(driver).__name__):
                    display = Display(rotation=rotation, driver=driver)
                    self.assertEqual((display.width, display.height), expected)
                    self.assertEqual((driver.width, driver.height), (800, 480))

    def marked_canvas(self, rotation, mode):
        size = (480, 800) if rotation in (90, 270) else (800, 480)
        width, height = size
        image = Image.new(mode, size, 255)
        points = ((2, 3), (width - 5, 7), (11, height - 13), (width - 17, height - 19))
        values = (0, 0, 0, 0) if mode == "1" else (0, 85, 170, 0)
        for point, value in zip(points, values):
            image.putpixel(point, value)
        return image, dict(zip(points, values))

    def assert_markers(self, actual, source, markers, rotation):
        self.assertEqual(actual.size, (800, 480))
        self.assertEqual(actual.mode, source.mode)
        for point, value in markers.items():
            self.assertEqual(actual.getpixel(panel_point(point, source.size, rotation)), value)
        # The exact nonwhite count also catches cropping and black padding bands.
        self.assertEqual(sum(count for count, value in actual.getcolors() if value != 255), len(markers))

    def test_monochrome_markers_reach_all_physical_corners(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source, markers = self.marked_canvas(rotation, "1")
                driver = hardware(rotation)
                driver.render_image(source)
                self.assert_markers(driver.driver.image, source, markers, rotation)

    def test_four_gray_markers_reach_all_physical_corners(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source, markers = self.marked_canvas(rotation, "L")
                driver = hardware(rotation)
                display = Display(rotation=rotation, driver=driver)
                self.assertEqual(display.render_photo(source, mode="4gray"), "4gray")
                self.assert_markers(driver.driver.image, source, markers, rotation)

    def test_monochrome_photos_stay_full_bleed_and_rotate_once(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source, markers = self.marked_canvas(rotation, "1")
                driver = hardware(rotation)
                display = Display(rotation=rotation, driver=driver)
                self.assertEqual(display.render_photo(source), "1bit_floyd")
                self.assert_markers(driver.driver.image, source, markers, rotation)

    def test_white_canvas_remains_white_without_rotation_padding(self):
        for rotation in (0, 90, 180, 270):
            driver = hardware(rotation)
            display = Display(rotation=rotation, driver=driver)
            for mode, prepare in (("1", driver._prepare_image), ("L", driver._prepare_four_gray_image)):
                with self.subTest(rotation=rotation, mode=mode):
                    actual = prepare(Image.new(mode, (display.width, display.height), 255))
                    self.assertEqual(actual.size, (800, 480))
                    self.assertEqual(actual.getextrema(), (255, 255))

    def test_text_is_drawn_on_logical_canvas_before_hardware_rotation(self):
        for rotation in (90, 270):
            driver = hardware(rotation)
            display = Display(rotation=rotation, driver=driver)
            for renderer in (driver.render_text, display.render_text):
                with self.subTest(rotation=rotation, renderer=renderer.__qualname__):
                    with patch.object(driver, "render_image", wraps=driver.render_image) as render:
                        renderer("Portrait text")
                    self.assertEqual(render.call_args.args[0].size, (480, 800))
                    self.assertEqual(driver.driver.image.size, (800, 480))
                    self.assertEqual(driver.driver.image.getextrema(), (0, 255))

    def test_module_border_is_applied_before_portrait_rotation(self):
        for rotation in (90, 270):
            with self.subTest(rotation=rotation):
                driver = hardware(rotation)
                display = Display(rotation=rotation, driver=driver)
                source = Image.new("1", (display.width, display.height), 255)
                markers = ((40, 42), (display.width - 45, display.height - 47))
                for point in markers:
                    source.putpixel(point, 0)
                display.render(source)
                actual = driver.driver.image
                self.assertEqual(actual.size, (800, 480))
                for point in markers:
                    self.assertEqual(actual.getpixel(panel_point(point, source.size, rotation)), 0)
                self.assertEqual(actual.getpixel((0, 0)), 0)
                self.assertEqual(actual.getpixel((400, 240)), 255)


if __name__ == "__main__":
    unittest.main()
