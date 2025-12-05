# app/modules/clock.py

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import DEFAULT_LAYOUTS, LayoutPreset

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

    def _get_text_size(self, draw: ImageDraw.Draw, text: str, font: Any) -> Tuple[int, int]:
        """Compatible text size calculator for new and old Pillow versions."""
        try:
            # Modern Pillow (>=10.0.0)
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        except AttributeError:
            # Older Pillow
            return draw.textsize(text, font=font)

    def _render_full(self, width: int, height: int) -> Image.Image:
        """Classic full-screen light layout used before layout presets."""
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        now = datetime.now()
        time_str = now.strftime(self.time_format)
        date_str = now.strftime(self.date_format)

        header_height = int(height * 0.22)
        header_inset = 24
        body_padding = 32

        draw.rounded_rectangle(
            [
                (header_inset, header_inset),
                (width - header_inset, header_height - header_inset),
            ],
            radius=18,
            fill=0,
        )

        header_font = self.fonts.get("large", self.fonts.get("default"))
        hw, hh = self._get_text_size(draw, header_text, header_font)
        hx = (width - hw) // 2
        hy = header_inset + ((header_height - (header_inset * 2)) - hh) // 2
        draw.text((hx, hy), header_text, font=header_font, fill=255)

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

        time_w, time_h = self._get_text_size(draw, time_str, self.time_font)
        date_w, date_h = self._get_text_size(draw, date_str, self.date_font)

        time_x = (width - time_w) // 2
        time_y = header_height + 24

        date_x = (width - date_w) // 2
        date_y = time_y + time_h + 20

        draw.text((time_x, time_y), time_str, font=self.time_font, fill=0)
        draw.text((date_x, date_y), date_str, font=self.date_font, fill=0)

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

        col_width = (x1 - x0) // 3
        col_centers = [x0 + col_width * i + col_width // 2 for i in range(3)]
        content_top = y0 + 18

        for idx, (label, value) in enumerate(zip(labels, temps)):
            lw, lh = self._get_text_size(draw, label, label_font)
            vw, vh = self._get_text_size(draw, value, value_font)
            cx = col_centers[idx]
            draw.text((cx - lw // 2, content_top), label, font=label_font, fill=text_fill)
            draw.text((cx - vw // 2, content_top + lh + 8), value, font=value_font, fill=text_fill)

        draw.line([(x0 + col_width, y0 + 10), (x0 + col_width, y1 - 10)], fill=text_fill, width=1)
        draw.line([(x0 + 2 * col_width, y0 + 10), (x0 + 2 * col_width, y1 - 10)], fill=text_fill, width=1)

        if self.last_weather_fetch:
            age = datetime.now() - self.last_weather_fetch
            minutes = int(age.total_seconds() // 60)
            updated_text = f"Updated {minutes}m ago"
            footer_font = self.fonts.get("small", label_font)
            fw, fh = self._get_text_size(draw, updated_text, footer_font)
            draw.text((x1 - fw - 10, y1 - fh - 8), updated_text, font=footer_font, fill=text_fill)

    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        layout = self._resolve_layout(kwargs.get("layout"))
        slots = self._layout_slots(layout, width, height)

        now = datetime.now()
        fallback_box = (0, 0, width, height)
        primary_box = self._pick_slot(slots, ("main", "primary", "row1_left", "top_left", "a"), fallback_box)
        secondary_box = None
        for key in ("secondary", "row1_right", "top_right", "bottom_left", "bottom_right", "b", "c", "d", "e"):
            if key in slots:
                secondary_box = slots[key]
                break

        header_text = self.location_label or "Today"
        last_text_y = self._draw_time_card(draw, primary_box, now, header_text)

        if secondary_box:
            self._draw_weather_card(draw, secondary_box, invert=layout.compact)
        else:
            _, y0, x1, _ = primary_box
            weather_area = (primary_box[0], last_text_y + 18, x1, height - 10)
            self._draw_weather_card(draw, weather_area, top_pad=0, invert=False)

        return image

    def _resolve_layout(self, layout_hint: Optional[Any]) -> LayoutPreset:
        if isinstance(layout_hint, LayoutPreset):
            return layout_hint
        if isinstance(layout_hint, str):
            return self._layout_lookup.get(layout_hint, self._default_layout)
        return self._default_layout

    def _find_first_fit(self, columns: int, rows: int, colspan: int, rowspan: int, occupied: list[list[bool]]) -> Optional[Tuple[int, int]]:
        for row in range(rows):
            for col in range(columns):
                if row + rowspan > rows or col + colspan > columns:
                    continue
                if any(
                    occupied[r][c]
                    for r in range(row, row + rowspan)
                    for c in range(col, col + colspan)
                ):
                    continue
                for r in range(row, row + rowspan):
                    for c in range(col, col + colspan):
                        occupied[r][c] = True
                return col, row
        return None

    def _layout_slots(self, layout: LayoutPreset, width: int, height: int) -> Dict[str, Tuple[int, int, int, int]]:
        cell_w = width / layout.columns
        cell_h = height / layout.rows
        occupied = [[False for _ in range(layout.columns)] for _ in range(layout.rows)]
        slots: Dict[str, Tuple[int, int, int, int]] = {}

        for slot in layout.slots:
            start = self._find_first_fit(layout.columns, layout.rows, slot.colspan, slot.rowspan, occupied)
            if start is None:
                continue
            col, row = start
            x0 = int(round(col * cell_w))
            y0 = int(round(row * cell_h))
            x1 = int(round((col + slot.colspan) * cell_w))
            y1 = int(round((row + slot.rowspan) * cell_h))
            slots[slot.key] = (x0, y0, x1, y1)

        return slots

    def _inset_box(self, box: Tuple[int, int, int, int], padding: int) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        return x0 + padding, y0 + padding, x1 - padding, y1 - padding

    def _pick_slot(self, slots: Dict[str, Tuple[int, int, int, int]], keys: Tuple[str, ...], fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        for key in keys:
            if key in slots:
                return slots[key]
        return fallback

    def _draw_time_card(
        self,
        draw: ImageDraw.Draw,
        box: Tuple[int, int, int, int],
        now: datetime,
        header_text: str,
    ) -> int:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=18, outline=0, width=2)

        header_font = self.fonts.get("large", self.fonts.get("default"))
        header_w, header_h = self._get_text_size(draw, header_text, header_font)
        header_y = y0 + 12
        draw.text(((x0 + x1 - header_w) // 2, header_y), header_text, font=header_font, fill=0)

        time_str = now.strftime(self.time_format)
        date_str = now.strftime(self.date_format)
        time_w, time_h = self._get_text_size(draw, time_str, self.time_font)
        date_w, date_h = self._get_text_size(draw, date_str, self.date_font)

        center_x = (x0 + x1) // 2
        time_y = header_y + header_h + 14
        date_y = time_y + time_h + 16

        draw.text((center_x - time_w // 2, time_y), time_str, font=self.time_font, fill=0)
        draw.text((center_x - date_w // 2, date_y), date_str, font=self.date_font, fill=0)

        return date_y + date_h

    def _draw_weather_card(
        self,
        draw: ImageDraw.Draw,
        box: Tuple[int, int, int, int],
        top_pad: int = 0,
        invert: bool = False,
    ) -> None:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        if top_pad:
            y0 = max(y0, y0 + top_pad)
        bg_fill = 0 if invert else None
        text_fill = 255 if invert else 0
        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=16, outline=0, width=2, fill=bg_fill)

        label_font = self.fonts.get("default")
        value_font = self.fonts.get("large", self.fonts.get("default"))

        temps = [
            self._format_temperature(self.weather.get("current"), fallback="--"),
            self._format_temperature(self.weather.get("high"), fallback="--"),
            self._format_temperature(self.weather.get("low"), fallback="--"),
        ]
        labels = ["Now", "High", "Low"]

        col_width = (x1 - x0) // 3
        col_centers = [x0 + col_width * i + col_width // 2 for i in range(3)]
        content_top = y0 + 18

        for idx, (label, value) in enumerate(zip(labels, temps)):
            lw, lh = self._get_text_size(draw, label, label_font)
            vw, vh = self._get_text_size(draw, value, value_font)
            cx = col_centers[idx]
            draw.text((cx - lw // 2, content_top), label, font=label_font, fill=text_fill)
            draw.text((cx - vw // 2, content_top + lh + 8), value, font=value_font, fill=text_fill)

        draw.line([(x0 + col_width, y0 + 10), (x0 + col_width, y1 - 10)], fill=text_fill, width=1)
        draw.line([(x0 + 2 * col_width, y0 + 10), (x0 + 2 * col_width, y1 - 10)], fill=text_fill, width=1)

        if self.last_weather_fetch:
            age = datetime.now() - self.last_weather_fetch
            minutes = int(age.total_seconds() // 60)
            updated_text = f"Updated {minutes}m ago"
            footer_font = self.fonts.get("small", label_font)
            fw, fh = self._get_text_size(draw, updated_text, footer_font)
            draw.text((x1 - fw - 10, y1 - fh - 8), updated_text, font=footer_font, fill=text_fill)

    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        layout = self._resolve_layout(kwargs.get("layout"))
        if layout.name == "full":
            return self._render_full(width, height)

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        now = datetime.now()
        fallback_box = (0, 0, width, height)
        slots = self._layout_slots(layout, width, height)
        primary_box = self._pick_slot(slots, ("main", "primary", "row1_left", "top_left", "a"), fallback_box)
        secondary_box = None
        for key in ("secondary", "row1_right", "top_right", "bottom_left", "bottom_right", "b", "c", "d", "e"):
            if key in slots:
                secondary_box = slots[key]
                break

        header_text = self.location_label or "Today"
        last_text_y = self._draw_time_card(draw, primary_box, now, header_text)

        if secondary_box:
            self._draw_weather_card(draw, secondary_box, invert=layout.compact)
        else:
            _, y0, x1, _ = primary_box
            weather_area = (primary_box[0], last_text_y + 18, x1, height - 10)
            self._draw_weather_card(draw, weather_area, top_pad=0, invert=False)

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

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (
            self._layout_lookup.get("wide_left", DEFAULT_LAYOUTS[1]),
            self._layout_lookup.get("full", self._default_layout),
            self._layout_lookup.get("quads", DEFAULT_LAYOUTS[4]),
            self._layout_lookup.get("compact_quads", DEFAULT_LAYOUTS[5]),
        )
