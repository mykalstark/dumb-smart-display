from typing import Optional, Protocol


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
    def __init__(self, rotation: int = 0) -> None:
        self.rotation = rotation
        # Placeholder for real initialization logic (SPI/I2C, etc.)
        print("[Display] Hardware driver initialized (rotation=%s)." % rotation)

    def render_text(self, text: str) -> None:
        # In real hardware mode, this method would render to the display buffer.
        print("[Display][HW] Rendering text:")
        print(text)

    def render_image(self, image: object) -> None:
        print("[Display][HW] Rendering image object: %s" % type(image))


class Display:
    def __init__(self, simulate: bool = True, rotation: int = 0, driver: Optional[DisplayDriver] = None):
        self.simulate = simulate
        self.rotation = rotation
        self.driver: DisplayDriver = driver or self._select_driver()

    def _select_driver(self) -> DisplayDriver:
        if self.simulate:
            return SimulatorDisplayDriver(rotation=self.rotation)
        return HardwareDisplayDriver(rotation=self.rotation)

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
