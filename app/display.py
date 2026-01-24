import importlib
import sys
from pathlib import Path
from typing import Dict, Optional, Protocol

from PIL import Image, ImageDraw, ImageFont


class DisplayDriver(Protocol):
    width: int
    height: int

    def render_text(self, text: str) -> None: ...

    def render_image(self, image: object) -> None: ...


class SimulatorDisplayDriver:
    def __init__(self, rotation: int = 0, width: int = 800, height: int = 480) -> None:
        self.rotation = rotation
        self.width = width
        self.height = height
        print(
            "[Display] Simulator driver initialized "
            f"(rotation={rotation}, size={width}x{height})."
        )

    def render_text(self, text: str) -> None:
        print("========== DISPLAY (SIM) ==========")
        print(text)
        print("===================================")

    def render_image(self, image: object) -> None:
        print("[Display] Simulator received image object: %s" % type(image))


class HardwareDisplayDriver:
    def __init__(
        self,
        rotation: int = 0,
        driver_name: str = "epd7in5_V2",
        library_path: Optional[str] = None,
        pin_config: Optional[Dict[str, int]] = None,
    ) -> None:
        self.rotation = rotation
        self.driver_name = driver_name
        self.pin_config = pin_config or {}
        self.library_path = library_path

        self._ensure_library_path()

        # The library file on disk should now have RST=5 (patched by install.sh),
        # so this import is safe and won't grab GPIO 17.
        import waveshare_epd.epdconfig as epdconfig  # type: ignore

        self.epdconfig = epdconfig

        # Apply any other config overrides (e.g. busy pin)
        self._apply_simple_overrides()

        driver_module = importlib.import_module(f"waveshare_epd.{self.driver_name}")
        self.driver = driver_module.EPD()

        self._fast_display = None
        self._full_refresh_rate = 10  # Perform a full refresh every 10 updates
        self._refresh_counter = self._full_refresh_rate  # Force full refresh on first render
        
        try:
            print("[Display] Initializing driver...")
            # This will open the pins defined in epdconfig.py
            self.driver.init()
            
            # Explicitly clear the display on boot to prevent ghosting from previous sessions
            print("[Display] Clearing display...")
            if hasattr(self.driver, "Clear"):
                try:
                    self.driver.Clear(0xFF)
                except TypeError:
                    self.driver.Clear()
            
            print("[Display] Driver init successful.")
        except Exception as e:
            print(f"[Display] CRITICAL: Driver init crashed: {e}")
            raise

        self.width = self.driver.width
        self.height = self.driver.height

        self._fast_display = self._detect_fast_display_method()

        print(
            "[Display] Hardware driver initialized "
            f"(rotation={rotation}, driver={driver_name}, size={self.width}x{self.height})."
        )

    def _detect_fast_display_method(self):
        candidates = [
            "display_partial",
            "displayPartial",
            "display_Partial",
            "display_fast",
            "displayFast",
        ]

        for name in candidates:
            method = getattr(self.driver, name, None)
            if callable(method):
                print(f"[Display] Using fast display method: {name}")
                return method

        return None

    def _ensure_library_path(self) -> None:
        if not self.library_path:
            return

        lib_path = Path(self.library_path).expanduser().resolve()
        if lib_path.is_dir() and str(lib_path) not in sys.path:
            sys.path.append(str(lib_path))

    def _apply_simple_overrides(self) -> None:
        """
        Simple variable updates for non-critical pins.
        We assume the critical conflict (RST=17) was resolved by patching the file on disk.
        """
        pin_map = {
            "rst": "RST_PIN",
            "dc": "DC_PIN",
            "busy": "BUSY_PIN",
            "cs": "CS_PIN",
            "mosi": "MOSI_PIN",
            "sclk": "SCLK_PIN",
        }

        for key, attr in pin_map.items():
            if key in self.pin_config:
                val = int(self.pin_config[key])
                # Only update if different, to avoid touching the object unnecessarily
                if hasattr(self.epdconfig, attr) and getattr(self.epdconfig, attr) != val:
                    setattr(self.epdconfig, attr, val)

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        # Resize first
        img = image.resize((self.width, self.height))
        # Rotate if needed
        if self.rotation:
            img = img.rotate(self.rotation, expand=False)
        
        # Convert to 1-bit using Thresholding (sharper text) instead of Dithering
        # 1. Convert to Grayscale ('L')
        # 2. Apply threshold: pixels < 128 becomes 0 (black), others 255 (white)
        # 3. Convert to Binary ('1')
        return img.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

    def render_text(self, text: str) -> None:
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except Exception:
            font = ImageFont.load_default()

        draw.multiline_text((10, 10), text, font=font, fill=0, spacing=4)
        # Render via the main pipeline so it handles init/sleep
        self.render_image(image)

    def render_image(self, image: object) -> None:
        if not isinstance(image, Image.Image):
            raise TypeError("HardwareDisplayDriver expects a PIL.Image for render_image")

        try:
            # Wake up the display
            self.driver.init()

            prepared = self._prepare_image(image)
            buffer = self.driver.getbuffer(prepared)

            # Increment refresh counter
            self._refresh_counter += 1

            # Check if we should force a full refresh
            if self._refresh_counter >= self._full_refresh_rate:
                print(f"[Display] Triggering scheduled full refresh (count={self._refresh_counter}).")
                self._refresh_counter = 0
                self.driver.display(buffer)
            elif self._fast_display:
                try:
                    self._fast_display(buffer)
                except Exception as exc:
                    print(f"[Display] Fast display failed ({exc}); falling back to full refresh.")
                    self.driver.display(buffer)
            else:
                self.driver.display(buffer)

        finally:
            # Always put display to sleep to prevent burn-in/fading
            self.driver.sleep()


class Display:
    def __init__(
        self,
        simulate: bool = True,
        rotation: int = 0,
        driver: Optional[DisplayDriver] = None,
        driver_name: str = "epd7in5_V2",
        library_path: Optional[str] = None,
        pin_config: Optional[Dict[str, int]] = None,
    ):
        self.simulate = simulate
        self.rotation = rotation
        self.driver_name = driver_name
        self.library_path = library_path
        self.pin_config = pin_config
        self.driver: DisplayDriver = driver or self._select_driver()

    def _select_driver(self) -> DisplayDriver:
        if self.simulate:
            return SimulatorDisplayDriver(rotation=self.rotation)
        return HardwareDisplayDriver(
            rotation=self.rotation,
            driver_name=self.driver_name,
            library_path=self.library_path,
            pin_config=self.pin_config,
        )

    def render(self, content: object) -> None:
        if isinstance(content, str):
            self.render_text(content)
            return

        if hasattr(content, "size") and hasattr(content, "mode"):
            self.render_image(self._add_border(content))
            return

        self.render_text(str(content))

    def render_text(self, text: str) -> None:
        image = self._render_text_image(text)
        self.render_image(image)

    def render_image(self, image: object) -> None:
        self.driver.render_image(image)

    def _render_text_image(self, text: str) -> Image.Image:
        width = getattr(self.driver, "width", 800)
        height = getattr(self.driver, "height", 480)

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        except Exception:
            font = ImageFont.load_default()

        text_w, text_h = draw.textsize(text, font=font)
        x = (width - text_w) // 2
        y = (height - text_h) // 2

        draw.text((x, y), text, font=font, fill=0)
        return self._add_border(image)

    def _add_border(self, image: Image.Image, thickness: int = 8, inset: int = 6) -> Image.Image:
        bordered = image.copy()
        draw = ImageDraw.Draw(bordered)

        outer = [0, 0, bordered.width - 1, bordered.height - 1]
        inner = [
            outer[0] + thickness,
            outer[1] + thickness,
            outer[2] - thickness,
            outer[3] - thickness,
        ]

        draw.rectangle(outer, outline=0, width=thickness)

        if inset > 0:
            inset_rect = [
                inner[0] + inset,
                inner[1] + inset,
                inner[2] - inset,
                inner[3] - inset,
            ]
            draw.rectangle(inset_rect, outline=0, width=2)

        return bordered
