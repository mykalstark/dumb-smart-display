# app/modules/clock.py

from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

class Module:
    name = "clock"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts
        
        # Configurable formats with defaults
        self.time_format = self.config.get("time_format", "%H:%M")
        self.date_format = self.config.get("date_format", "%a, %b %d")
        
        # Try to load custom sizes from config (e.g. time_size: 120)
        # We try to load the bold font directly to get specific sizes.
        self.time_font = self._load_custom_font("time_size", 100, "large")
        self.date_font = self._load_custom_font("date_size", 40, "default")

    def _load_custom_font(self, size_key: str, default_size: int, fallback_font_key: str) -> Any:
        """
        Attempt to load a font of a specific size defined in config.
        Falls back to the shared 'fonts' dict if that fails.
        """
        target_size = self.config.get(size_key, default_size)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        
        try:
            return ImageFont.truetype(font_path, target_size)
        except IOError:
            # If the specific font file isn't found, use the one passed from main.py
            return self.fonts.get(fallback_font_key, ImageFont.load_default())

    def _get_text_size(self, draw: ImageDraw.Draw, text: str, font: Any) -> Tuple[int, int]:
        """Compatible text size calculator for new and old Pillow versions."""
        try:
            # Modern Pillow (>=10.0.0)
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        except AttributeError:
            # Older Pillow
            return draw.textsize(text, font=font)

    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        # Create a white canvas (mode '1' for 1-bit color)
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)
        
        now = datetime.now()
        time_str = now.strftime(self.time_format)
        date_str = now.strftime(self.date_format)
        
        # Calculate sizes
        time_w, time_h = self._get_text_size(draw, time_str, self.time_font)
        date_w, date_h = self._get_text_size(draw, date_str, self.date_font)

        # Calculate positions (Centered with breathing room)
        vertical_padding = 40
        total_h = time_h + date_h + 30  # 30px padding between time and date
        available_height = max(height - (vertical_padding * 2), total_h)
        start_y = vertical_padding + (available_height - total_h) // 2

        time_x = (width - time_w) // 2
        time_y = start_y

        date_x = (width - date_w) // 2
        date_y = time_y + time_h + 30
        
        # Draw
        draw.text((time_x, time_y), time_str, font=self.time_font, fill=0)
        draw.text((date_x, date_y), date_str, font=self.date_font, fill=0)
        
        return image

    def tick(self) -> None:
        pass

    def handle_button(self, event: str) -> None:
        # Clock currently ignores button presses.
        return

    def refresh_interval(self) -> Optional[int]:
        return None
