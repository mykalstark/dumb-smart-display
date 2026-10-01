"""7-day weather forecast module using Open-Meteo (free, no API key)."""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    PAGE_HEADER_H, DIVIDER_W, LINE_SPACING,
    draw_page_header, fit_header_font,
)

log = logging.getLogger(__name__)

# Path to the bundled Weather Icons font (MIT licence, Erik Flowers)
# https://github.com/erikflowers/weather-icons
_ICON_FONT_PATH = Path(__file__).parent.parent / "assets" / "fonts" / "weathericons-regular-webfont.ttf"

# ---------------------------------------------------------------------------
# WMO weather code → icon type mapping
# https://open-meteo.com/en/docs#weathervariables
# ---------------------------------------------------------------------------
def _wmo_to_icon(code: int) -> str:
    if code <= 1:
        return "sun"
    if code == 2:
        return "sun_cloud"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloud"


# Weather Icons font codepoints (PUA unicode, weather-icons by Erik Flowers, MIT)
_WMO_GLYPH: Dict[str, int] = {
    "sun":       0xf00d,  # wi-day-sunny
    "sun_cloud": 0xf002,  # wi-day-cloudy
    "cloud":     0xf013,  # wi-cloudy
    "fog":       0xf014,  # wi-fog
    "drizzle":   0xf01c,  # wi-sprinkle
    "rain":      0xf019,  # wi-rain
    "snow":      0xf01b,  # wi-snow
    "storm":     0xf01e,  # wi-thunderstorm
}


# ---------------------------------------------------------------------------
# Geometric icon drawing helpers — fallback when icon font is unavailable.
# All icons are drawn centred on (cx, cy) within a bounding box of ~size px.
# ---------------------------------------------------------------------------

def _draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    r = size // 4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=2)
    ray_inner = r + 4
    ray_outer = r + size // 5
    for i in range(8):
        angle = math.radians(i * 45)
        x1 = cx + ray_inner * math.cos(angle)
        y1 = cy + ray_inner * math.sin(angle)
        x2 = cx + ray_outer * math.cos(angle)
        y2 = cy + ray_outer * math.sin(angle)
        draw.line([(x1, y1), (x2, y2)], fill=0, width=2)


def _draw_cloud_shape(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, h: int, *, filled: bool = False
) -> None:
    """Draw a simple stylised cloud centred on (cx, cy) with the given width/height."""
    fill = 0 if filled else None
    bx0, by0, bx1, by1 = cx - w // 2, cy - h // 4, cx + w // 2, cy + h // 4
    draw.ellipse([bx0, by0, bx1, by1], outline=0, width=2, fill=fill)
    lbr = h // 3
    draw.ellipse(
        [cx - w // 3 - lbr, cy - h // 4 - lbr, cx - w // 3 + lbr, cy - h // 4 + lbr],
        outline=0, width=2, fill=fill,
    )
    cbr = int(h * 0.42)
    draw.ellipse(
        [cx - cbr, cy - h // 4 - cbr, cx + cbr, cy - h // 4 + cbr],
        outline=0, width=2, fill=fill,
    )
    rbr = h // 4
    draw.ellipse(
        [cx + w // 5 - rbr, cy - h // 4 - rbr, cx + w // 5 + rbr, cy - h // 4 + rbr],
        outline=0, width=2, fill=fill,
    )


def _draw_cloud(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    _draw_cloud_shape(draw, cx, cy, int(size * 0.9), size // 2)


def _draw_sun_cloud(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    sun_cx = cx - size // 5
    sun_cy = cy - size // 6
    sun_r = size // 6
    draw.ellipse(
        [sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r],
        outline=0, width=2,
    )
    ray_i = sun_r + 3
    ray_o = sun_r + 7
    for i in range(8):
        angle = math.radians(i * 45)
        draw.line(
            [(sun_cx + ray_i * math.cos(angle), sun_cy + ray_i * math.sin(angle)),
             (sun_cx + ray_o * math.cos(angle), sun_cy + ray_o * math.sin(angle))],
            fill=0, width=1,
        )
    cloud_cx = cx + size // 8
    cloud_cy = cy + size // 8
    _draw_cloud_shape(draw, cloud_cx, cloud_cy, int(size * 0.65), size // 3)


def _draw_rain(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, *, heavy: bool = False) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 7
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.85), cloud_h)
    drop_count = 4 if heavy else 3
    spacing = size // (drop_count + 1)
    drop_len = size // 5
    drop_top = cloud_top_cy + cloud_h // 2 + 6
    for i in range(drop_count):
        x = cx - size // 3 + i * spacing + spacing // 2
        draw.line([(x, drop_top), (x - 5, drop_top + drop_len)], fill=0, width=2)


def _draw_drizzle(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 7
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.85), cloud_h)
    drop_top = cloud_top_cy + cloud_h // 2 + 8
    for i in range(3):
        x = cx - size // 4 + i * (size // 4)
        draw.ellipse([x - 2, drop_top, x + 2, drop_top + 4], fill=0)
        draw.ellipse([x - 2, drop_top + 10, x + 2, drop_top + 14], fill=0)


def _draw_snow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 8
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.85), cloud_h)
    dot_top = cloud_top_cy + cloud_h // 2 + 8
    for i in range(3):
        x = cx - size // 3 + i * (size // 3) + size // 6
        y = dot_top
        r = 3
        for angle_deg in (0, 60, 120):
            ang = math.radians(angle_deg)
            draw.line(
                [(x - r * math.cos(ang), y - r * math.sin(ang)),
                 (x + r * math.cos(ang), y + r * math.sin(ang))],
                fill=0, width=2,
            )
        x2 = cx - size // 6 + i * (size // 3)
        y2 = dot_top + size // 6
        for angle_deg in (0, 60, 120):
            ang = math.radians(angle_deg)
            draw.line(
                [(x2 - r * math.cos(ang), y2 - r * math.sin(ang)),
                 (x2 + r * math.cos(ang), y2 + r * math.sin(ang))],
                fill=0, width=2,
            )


def _draw_storm(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 5
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.9), cloud_h, filled=True)
    bolt_top = cloud_top_cy + cloud_h // 2 + 4
    bolt_w = size // 5
    bolt_h = size // 3
    pts = [
        (cx + bolt_w // 2, bolt_top),
        (cx, bolt_top + bolt_h // 2),
        (cx + bolt_w // 3, bolt_top + bolt_h // 2),
        (cx - bolt_w // 2, bolt_top + bolt_h),
    ]
    draw.line(pts, fill=255, width=3)


def _draw_fog(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    line_w = int(size * 0.8)
    spacing = size // 4
    for i in range(3):
        y = cy - spacing + i * spacing
        x0, x1 = cx - line_w // 2, cx + line_w // 2
        draw.rounded_rectangle([x0, y - 3, x1, y + 3], radius=3, fill=0)


def _draw_icon(
    draw: ImageDraw.ImageDraw, icon: str, cx: int, cy: int, size: int
) -> None:
    dispatch = {
        "sun": _draw_sun,
        "sun_cloud": _draw_sun_cloud,
        "cloud": _draw_cloud,
        "rain": _draw_rain,
        "drizzle": _draw_drizzle,
        "snow": _draw_snow,
        "storm": _draw_storm,
        "fog": _draw_fog,
    }
    fn = dispatch.get(icon, _draw_cloud)
    fn(draw, cx, cy, size)


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class Module(BaseDisplayModule):
    name = "weather_forecast"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        # Location comes from module config OR injected from top-level location:
        self.latitude: Optional[float] = self._float(self.config.get("latitude"))
        self.longitude: Optional[float] = self._float(self.config.get("longitude"))
        self.temperature_unit: str = self.config.get("temperature_unit", "fahrenheit")
        self.location_name: str = self.config.get("location_name", "7-Day Forecast")
        self.refresh_seconds: int = int(self.config.get("refresh_seconds", 3600))

        self._days: List[Dict[str, Any]] = []
        self._last_fetch: Optional[datetime] = None
        self._error: Optional[str] = None

        # Cache for loaded icon fonts keyed by size; None availability flag
        # is set on first load attempt so we only log the warning once.
        self._icon_font_cache: Dict[int, Any] = {}
        self._icon_font_available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _float(val: Any) -> Optional[float]:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _unit_is_fahrenheit(self) -> bool:
        return str(self.temperature_unit).lower().startswith("f")

    def _fmt_temp(self, val: Optional[float]) -> str:
        if val is None:
            return "--"
        sym = "°F" if self._unit_is_fahrenheit() else "°C"
        return f"{round(val)}{sym}"

    def _fmt_precip(self, val: Optional[float]) -> str:
        if val is None or val <= 0:
            return ""
        if self._unit_is_fahrenheit():
            return f"{val:.2f}in".rstrip("0").rstrip(".")
        return f"{val:.1f}mm"

    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _load_font(self, size: int) -> Any:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            fallback = self.fonts.get("default") or ImageFont.load_default()
            if isinstance(fallback, ImageFont.FreeTypeFont):
                return fallback.font_variant(size=size)
            return fallback

    def _load_icon_font(self, size: int) -> Optional[Any]:
        """Load the bundled Weather Icons font at *size*.

        Returns the font object, or None if the font file is not present
        (in which case the module falls back to PIL-drawn icons).
        Only logs the missing-font warning once per module instance.
        """
        if self._icon_font_available is False:
            return None
        if size in self._icon_font_cache:
            return self._icon_font_cache[size]
        try:
            font = ImageFont.truetype(str(_ICON_FONT_PATH), size)
            self._icon_font_cache[size] = font
            self._icon_font_available = True
            return font
        except Exception:
            log.info(
                "weather_forecast: Weather Icons font not found at %s — using PIL fallback",
                _ICON_FONT_PATH,
            )
            self._icon_font_available = False
            return None

    def _fit_font(
        self, draw: ImageDraw.ImageDraw, texts: Sequence[str],
        width: int, height: int, max_size: int, *, icon: bool = False,
    ) -> Optional[Any]:
        """Fit the whole row, including glyph bearings, in both dimensions.

        Use one font per row so a three-digit or negative temperature does not
        change the visual hierarchy from one column to the next.
        """
        loader = self._load_icon_font if icon else self._load_font
        for size in range(max_size, 0, -1):
            font = loader(size)
            if font is None:
                return None
            if all(
                w <= width and h <= height
                for w, h in (self._get_text_size(draw, text, font) for text in texts)
            ):
                return font
        return font

    @staticmethod
    def _draw_centered_text(
        draw: ImageDraw.ImageDraw, text: str, font: Any,
        box: Tuple[int, int, int, int],
    ) -> None:
        """Centre the visible glyph bounds, not the font's baseline origin."""
        x0, y0, x1, y1 = box
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        draw.text(
            (x0 + (x1 - x0 - (right - left)) // 2 - left,
             y0 + (y1 - y0 - (bottom - top)) // 2 - top),
            text, font=font, fill=0,
        )

    @staticmethod
    def _draw_fallback_icon(
        image: Image.Image, icon: str, box: Tuple[int, int, int, int],
    ) -> None:
        """Measure the geometric artwork too; its nominal size is approximate."""
        x0, y0, x1, y1 = box
        size = min(x1 - x0, y1 - y0)
        tile = Image.new("1", (size * 4, size * 4), 255)
        _draw_icon(ImageDraw.Draw(tile), icon, size * 2, size * 2, size)
        bounds = tile.point(lambda p: 255 - p).getbbox()
        if bounds is None:
            return
        tile = tile.crop(bounds)
        tile.thumbnail((x1 - x0, y1 - y0), Image.Resampling.NEAREST)
        image.paste(tile, (x0 + (x1 - x0 - tile.width) // 2,
                           y0 + (y1 - y0 - tile.height) // 2))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def tick(self) -> None:
        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch).total_seconds() < self.refresh_seconds:
            return
        self._fetch()

    def handle_button(self, event: str) -> None:
        if event == "refresh":
            self._fetch()

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    def _fetch(self) -> None:
        self._last_fetch = datetime.now()

        if self.latitude is None or self.longitude is None:
            self._error = "No location configured"
            return

        unit = "fahrenheit" if self._unit_is_fahrenheit() else "celsius"
        precip_unit = "inch" if self._unit_is_fahrenheit() else "mm"

        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
            "temperature_unit": unit,
            "precipitation_unit": precip_unit,
            "forecast_days": 7,
        }

        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("weather_forecast: fetch failed: %s", exc)
            self._error = "Weather unavailable"
            return

        daily = payload.get("daily", {})
        dates = daily.get("time", [])
        codes = daily.get("weather_code", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])
        precips = daily.get("precipitation_sum", [])

        self._days = []
        for i, date_str in enumerate(dates[:7]):
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            code = codes[i] if i < len(codes) else 0
            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            precip = precips[i] if i < len(precips) else 0.0

            self._days.append({
                "dt": dt,
                "day": dt.strftime("%a"),   # "Mon", "Tue", …
                "icon": _wmo_to_icon(int(code) if code is not None else 0),
                "high": high,
                "low": low,
                "precip": float(precip) if precip is not None else 0.0,
            })

        self._error = None

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self._fetch()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)
        if self._error or not self._days:
            msg = self._error or "No forecast data"
            font = self._fit_font(draw, [msg], width - 16, height - 16, 24)
            self._draw_centered_text(draw, msg, font, (8, 8, width - 8, height - 8))
            return image

        # Keep the row geometry independent of column width. Wider columns
        # (including a partial forecast) must not push later rows off-screen.
        days = self._days[:7]
        n_days = len(days)
        col_w = width // n_days
        header_h = min(PAGE_HEADER_H, height // 4)
        draw_page_header(
            draw, width, "7 Day Forecast",
            fit_header_font(draw, "7 Day Forecast", width, header_h), header_h,
        )
        body_top = header_h + 1
        body_h = height - body_top
        pad = min(12, body_h // 20)
        gap = min(LINE_SPACING, body_h // 40)
        inset = min(8, col_w // 10)

        # Reserve padding, all six gaps and the separator before distributing
        # the remaining height. Cumulative edges absorb rounding remainders.
        weights = (54, 100, 24, 52, 36, 24)  # day, icon, date, high, low, precip
        usable_h = body_h - 2 * pad - 6 * gap - DIVIDER_W
        rows = []
        y = body_top + pad
        used_weight = 0
        for weight in weights:
            row_h = (usable_h * (used_weight + weight) // sum(weights)
                     - usable_h * used_weight // sum(weights))
            rows.append((y, y + row_h))
            used_weight += weight
            y += row_h + gap
            if len(rows) == 3:
                separator_y = y
                y += DIVIDER_W + gap

        text_w = col_w - 2 * inset
        day_texts = [day["day"].upper() for day in days]
        date_texts = [str(day["dt"].day) for day in days]
        high_texts = [self._fmt_temp(day["high"]) for day in days]
        low_texts = [self._fmt_temp(day["low"]) for day in days]
        precip_texts = [self._fmt_precip(day["precip"]) for day in days]
        text_rows = (
            (0, day_texts, 60), (2, date_texts, 18),
            (3, high_texts, 32), (4, low_texts, 24), (5, precip_texts, 16),
        )
        fonts = {
            row: self._fit_font(draw, texts, text_w, rows[row][1] - rows[row][0], size)
            for row, texts, size in text_rows
        }
        # Size against every supported symbol, especially the wide partly-cloudy
        # glyph and tall sun/storm glyphs, rather than nominal font point size.
        icon_font = self._fit_font(
            draw, [chr(code) for code in _WMO_GLYPH.values()],
            text_w, rows[1][1] - rows[1][0],
            min(160, text_w, rows[1][1] - rows[1][0]), icon=True,
        )

        for i, day in enumerate(days):
            # Divide the actual canvas, without a minimum width or lost pixels.
            x0 = i * width // n_days
            x1 = (i + 1) * width // n_days
            if i > 0:
                draw.line([(x0, body_top + gap), (x0, height - gap - 1)],
                          fill=0, width=DIVIDER_W)
            if i == 0:
                draw.rectangle([(x0, body_top), (x1 - 1, body_top + 2)], fill=0)

            for row, texts, _ in text_rows:
                if texts[i]:
                    self._draw_centered_text(
                        draw, texts[i], fonts[row],
                        (x0 + inset, rows[row][0], x1 - inset, rows[row][1]),
                    )

            icon_box = (x0 + inset, rows[1][0], x1 - inset, rows[1][1])
            icon_type = day["icon"]
            if icon_font is not None:
                glyph = chr(_WMO_GLYPH.get(icon_type, _WMO_GLYPH["cloud"]))
                self._draw_centered_text(draw, glyph, icon_font, icon_box)
            else:
                self._draw_fallback_icon(image, icon_type, icon_box)

            draw.line([(x0 + inset, separator_y), (x1 - inset - 1, separator_y)],
                      fill=0, width=DIVIDER_W)

        return image
