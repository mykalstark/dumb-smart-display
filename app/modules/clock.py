# app/modules/clock.py

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

import requests
from PIL import Image, ImageDraw, ImageFont

class Module:
    name = "clock"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        # Configurable formats with defaults
        self.time_format = self.config.get("time_format", "%H:%M")
        self.date_format = self.config.get("date_format", "%a, %b %d")

        # Weather configuration
        self.latitude = self.config.get("latitude")
        self.longitude = self.config.get("longitude")
        self.temperature_unit = self.config.get("temperature_unit", "fahrenheit")
        self.weather_refresh_seconds = int(self.config.get("refresh_seconds", 1800))
        self.location_label = self.config.get("location_name", "Today")

        # Try to load custom sizes from config (e.g. time_size: 120)
        # We try to load the bold font directly to get specific sizes.
        self.time_font = self._load_custom_font("time_size", 100, "large")
        self.date_font = self._load_custom_font("date_size", 40, "default")

        self.weather: Dict[str, Optional[float]] = {
            "current": None,
            "high": None,
            "low": None,
        }
        self.last_weather_fetch: Optional[datetime] = None
        self.log = logging.getLogger(__name__)

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
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        now = datetime.now()
        time_str = now.strftime(self.time_format)
        date_str = now.strftime(self.date_format)

        header_height = int(height * 0.22)
        header_inset = 24
        body_padding = 32

        # Header bar similar to Mealie layout
        draw.rounded_rectangle(
            [
                (header_inset, header_inset),
                (width - header_inset, header_height - header_inset),
            ],
            radius=18,
            fill=0,
        )

        header_text = self.location_label or "Today"
        header_font = self.fonts.get("large", self.fonts.get("default"))
        hw, hh = self._get_text_size(draw, header_text, header_font)
        hx = (width - hw) // 2
        hy = header_inset + ((header_height - (header_inset * 2)) - hh) // 2
        draw.text((hx, hy), header_text, font=header_font, fill=255)

        # Divider shadow effect (double line)
        draw.line(
            [(header_inset, header_height), (width - header_inset, header_height)],
            fill=0,
            width=2,
        )
        draw.line(
            [(header_inset, header_height + 4), (width - header_inset, header_height + 4)],
            fill=0,
            width=1,
        )

        # Date + Time stack
        time_w, time_h = self._get_text_size(draw, time_str, self.time_font)
        date_w, date_h = self._get_text_size(draw, date_str, self.date_font)

        time_x = (width - time_w) // 2
        time_y = header_height + 24

        date_x = (width - date_w) // 2
        date_y = time_y + time_h + 20

        draw.text((time_x, time_y), time_str, font=self.time_font, fill=0)
        draw.text((date_x, date_y), date_str, font=self.date_font, fill=0)

        # Weather card styled like Mealie info cards
        card_top = date_y + date_h + 30
        card_height = 170
        card_left = body_padding
        card_right = width - body_padding
        card_bottom = min(card_top + card_height, height - body_padding)

        draw.rounded_rectangle(
            [(card_left, card_top), (card_right, card_bottom)],
            radius=16,
            outline=0,
            width=2,
        )

        label_font = self.fonts.get("default")
        value_font = self.fonts.get("large", self.fonts.get("default"))

        temps = [
            self._format_temperature(self.weather.get("current"), fallback="--"),
            self._format_temperature(self.weather.get("high"), fallback="--"),
            self._format_temperature(self.weather.get("low"), fallback="--"),
        ]
        labels = ["Now", "High", "Low"]

        col_width = (card_right - card_left) // 3
        col_centers = [card_left + col_width * i + col_width // 2 for i in range(3)]
        card_content_top = card_top + 24

        for idx, (label, value) in enumerate(zip(labels, temps)):
            lw, lh = self._get_text_size(draw, label, label_font)
            vw, vh = self._get_text_size(draw, value, value_font)
            cx = col_centers[idx]
            draw.text((cx - lw // 2, card_content_top), label, font=label_font, fill=0)
            draw.text(
                (cx - vw // 2, card_content_top + lh + 10),
                value,
                font=value_font,
                fill=0,
            )

        draw.line(
            [(card_left + col_width, card_top + 12), (card_left + col_width, card_bottom - 12)],
            fill=0,
            width=1,
        )
        draw.line(
            [
                (card_left + 2 * col_width, card_top + 12),
                (card_left + 2 * col_width, card_bottom - 12),
            ],
            fill=0,
            width=1,
        )

        # Small footer showing last update when available
        if self.last_weather_fetch:
            age = datetime.now() - self.last_weather_fetch
            minutes = int(age.total_seconds() // 60)
            updated_text = f"Weather updated {minutes}m ago"
            footer_font = self.fonts.get("small", label_font)
            fw, fh = self._get_text_size(draw, updated_text, footer_font)
            fx = width - body_padding - fw
            fy = card_bottom + 12
            if fy + fh < height - body_padding:
                draw.text((fx, fy), updated_text, font=footer_font, fill=0)

        return image

    def tick(self) -> None:
        if self.latitude is None or self.longitude is None:
            return

        now = datetime.now()
        if self.last_weather_fetch is None or (now - self.last_weather_fetch) > timedelta(
            seconds=self.weather_refresh_seconds
        ):
            self._fetch_weather()
            self.last_weather_fetch = now

    def _fetch_weather(self) -> None:
        base_url = "https://api.open-meteo.com/v1/forecast"
        unit = "fahrenheit" if str(self.temperature_unit).lower().startswith("f") else "celsius"

        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "current": "temperature_2m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "temperature_unit": unit,
        }

        try:
            response = requests.get(base_url, params=params, timeout=5)
            response.raise_for_status()
            payload = response.json()
            current_temp = payload.get("current", {}).get("temperature_2m")
            daily = payload.get("daily", {})
            highs = daily.get("temperature_2m_max") or []
            lows = daily.get("temperature_2m_min") or []
            high_temp = highs[0] if highs else None
            low_temp = lows[0] if lows else None

            self.weather.update({"current": current_temp, "high": high_temp, "low": low_temp})
        except Exception as exc:
            self.log.warning("Weather fetch failed: %s", exc)

    def _format_temperature(self, value: Optional[float], fallback: str = "--") -> str:
        if value is None:
            return fallback
        try:
            rounded = round(float(value))
        except (TypeError, ValueError):
            return fallback
        unit_symbol = "°F" if str(self.temperature_unit).lower().startswith("f") else "°C"
        return f"{rounded}{unit_symbol}"

    def handle_button(self, event: str) -> None:
        # Clock currently ignores button presses.
        return

    def refresh_interval(self) -> Optional[int]:
        return None
