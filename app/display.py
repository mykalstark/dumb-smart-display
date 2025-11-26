import importlib
import sys
from pathlib import Path
from typing import Dict, Optional, Protocol

from PIL import Image, ImageDraw, ImageFont


class DisplayDriver(Protocol):
    def render_text(self, text: str) -> None: ...

    def render_image(self, image: object) -> None: ...


class SimulatorDisplayDriver:
    def __init__(self, rotation: int = 0) -> None:
        self.rotation = rotation
        print("[Display] Simulator driver initialized (rotation=%s)." % rotation)

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

        import waveshare_epd.epdconfig as epdconfig  # type: ignore

        self.epdconfig = epdconfig
        self._apply_pin_overrides()

        driver_module = importlib.import_module(f"waveshare_epd.{self.driver_name}")
        self.driver = driver_module.EPD()
        self.driver.init()
        self.width = self.driver.width
        self.height = self.driver.height

        print(
            "[Display] Hardware driver initialized "
            f"(rotation={rotation}, driver={driver_name}, size={self.width}x{self.height})."
        )

    def _ensure_library_path(self) -> None:
        if not self.library_path:
            return

        lib_path = Path(self.library_path).expanduser().resolve()
        if lib_path.is_dir() and str(lib_path) not in sys.path:
            sys.path.append(str(lib_path))

    def _apply_pin_overrides(self) -> None:
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
                setattr(self.epdconfig, attr, int(self.pin_config[key]))

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        img = image.convert("1").resize((self.width, self.height))
        if self.rotation:
            img = img.rotate(self.rotation, expand=False)
        return img

    def render_text(self, text: str) -> None:
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except Exception:
            font = ImageFont.load_default()

        draw.multiline_text((10, 10), text, font=font, fill=0, spacing=4)
        prepared = self._prepare_image(image)
        self.driver.display(self.driver.getbuffer(prepared))

    def render_image(self, image: object) -> None:
        if not isinstance(image, Image.Image):
            raise TypeError("HardwareDisplayDriver expects a PIL.Image for render_image")

        prepared = self._prepare_image(image)
        self.driver.display(self.driver.getbuffer(prepared))


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
            self.render_image(content)
            return

        self.render_text(str(content))

    def render_text(self, text: str) -> None:
        self.driver.render_text(text)

    def render_image(self, image: object) -> None:
        self.driver.render_image(image)
