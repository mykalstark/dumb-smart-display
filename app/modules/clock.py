# app/modules/clock.py

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, LINE_SPACING, CARD_RADIUS,
    draw_card, draw_text_block, draw_metrics, page_body, layout_slots,
)

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

        self._default_layout = DEFAULT_LAYOUTS[0]
        self._layout_lookup = {layout.name: layout for layout in DEFAULT_LAYOUTS}

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

    def _render_full(self, width: int, height: int) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)
        x0, y0, x1, y1 = page_body(draw, width, height, self.location_label or "Today")
        split = y0 + (y1 - y0) * 3 // 5
        now = datetime.now()
        self._draw_time_content(draw, (x0, y0, x1, split - COL_GAP), now)
        self._draw_weather_card(draw, (x0, split, x1, y1))
        return image

    def _draw_time_content(self, draw, box, now):
        x0, y0, x1, y1 = box
        inset = min(INNER_PAD, max(2, (y1 - y0) // 12))
        split = y0 + (y1 - y0) * 2 // 3
        draw_text_block(draw, (x0 + inset, y0 + inset, x1 - inset, split),
                        now.strftime(self.time_format), self.time_font)
        draw_text_block(draw, (x0 + inset, split + LINE_SPACING, x1 - inset, y1 - inset),
                        now.strftime(self.date_format), self.date_font)

    def _resolve_layout(self, layout_hint: Optional[Any]) -> LayoutPreset:
        if isinstance(layout_hint, LayoutPreset):
            return layout_hint
        if isinstance(layout_hint, str):
            return self._layout_lookup.get(layout_hint, self._default_layout)
        return self._default_layout

    def _layout_slots(self, layout, width, height):
        return layout_slots(layout, width, height)

    def _pick_slot(self, slots: Dict[str, Tuple[int, int, int, int]], keys: Tuple[str, ...], fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        for key in keys:
            if key in slots:
                return slots[key]
        return fallback

    def _draw_time_card(self, draw, box, now, header_text):
        x0, y0, x1, y1 = box
        draw_card(draw, *box)
        header_bottom = y0 + (y1 - y0) // 4
        draw_text_block(draw, (x0 + INNER_PAD, y0 + INNER_PAD, x1 - INNER_PAD, header_bottom),
                        header_text, self.fonts.get("large", self.fonts.get("default")))
        self._draw_time_content(draw, (x0, header_bottom, x1, y1), now)
        return y1

    def _draw_weather_card(self, draw, box, top_pad=0, invert=False):
        x0, y0, x1, y1 = box
        draw.rounded_rectangle([(x0, y0), (x1 - 1, y1 - 1)], radius=CARD_RADIUS,
                               outline=0, width=2, fill=0 if invert else None)
        fill = 255 if invert else 0
        footer_h = min(28, (y1 - y0) // 5) if self.last_weather_fetch else 0
        draw_metrics(draw, (x0, y0, x1, y1 - footer_h), ["Now", "High", "Low"],
                     [self._format_temperature(self.weather.get(key)) for key in ("current", "high", "low")],
                     self.fonts.get("default"), self.fonts.get("large", self.fonts.get("default")), fill)
        if self.last_weather_fetch:
            minutes = int((datetime.now() - self.last_weather_fetch).total_seconds() // 60)
            draw_text_block(draw, (x0 + INNER_PAD, y1 - footer_h, x1 - INNER_PAD, y1 - 4),
                            f"Updated {minutes}m ago", self.fonts.get("small", self.fonts.get("default")), fill)

    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        layout = self._resolve_layout(kwargs.get("layout"))
        if layout.name == "full":
            return self._render_full(width, height)

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        now = datetime.now()
        fallback_box = (OUTER_PAD, OUTER_PAD, width - OUTER_PAD, height - OUTER_PAD)
        slots = self._layout_slots(layout, width, height)
        primary_box = self._pick_slot(slots, ("main", "primary", "row1_left", "top_left", "a"), fallback_box)
        secondary_box = None
        for key in ("secondary", "row1_right", "top_right", "bottom_left", "bottom_right", "b", "c", "d", "e"):
            if key in slots:
                secondary_box = slots[key]
                break

        if secondary_box is None:
            return self._render_full(width, height)
        if (primary_box[3] - primary_box[1] < 100 or secondary_box[2] - secondary_box[0] < 120
                or secondary_box[3] - secondary_box[1] < 100):
            return self._render_full(width, height)

        header_text = self.location_label or "Today"
        self._draw_time_card(draw, primary_box, now, header_text)
        self._draw_weather_card(draw, secondary_box, invert=layout.compact)

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

    def force_refresh(self) -> None:
        """Immediately fetch weather data regardless of the schedule."""

        if self.latitude is None or self.longitude is None:
            return

        self._fetch_weather()
        self.last_weather_fetch = datetime.now()

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

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (
            self._layout_lookup.get("wide_left", DEFAULT_LAYOUTS[1]),
            self._layout_lookup.get("full", self._default_layout),
            self._layout_lookup.get("quads", DEFAULT_LAYOUTS[4]),
            self._layout_lookup.get("compact_quads", DEFAULT_LAYOUTS[5]),
        )
