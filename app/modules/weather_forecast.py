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
    PAGE_HEADER_H, PAGE_HEADER_RX, PAGE_HEADER_RY, PAGE_HEADER_RADIUS,
    PAGE_HEADER_FONT_SIZE, DIVIDER_W, COL_GAP, LINE_SPACING,
    draw_page_header, get_text_size as _theme_get_text_size,
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
            return self.fonts.get("default")

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

    def _load_day_font(self, col_w: int) -> Any:
        """Return the largest Bold font size where 'WED' (widest day abbrev)
        fits within col_w minus 16 px of horizontal padding."""
        target_w = col_w - 16
        bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        # Probe from large → small in steps of 2 px
        for size in range(60, 18, -2):
            try:
                f = ImageFont.truetype(bold_path, size)
            except Exception:
                f = self.fonts.get("default")
            dummy = Image.new("1", (1, 1))
            dummy_draw = ImageDraw.Draw(dummy)
            max_w = max(
                self._get_text_size(dummy_draw, d, f)[0]
                for d in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            )
            if max_w <= target_w:
                return f
        return self._load_font(18)

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
        default_font = self.fonts.get("default")

        if self._error or not self._days:
            msg = self._error or "No forecast data"
            tw, th = self._get_text_size(draw, msg, default_font)
            draw.text(((width - tw) // 2, (height - th) // 2), msg, font=default_font, fill=0)
            return image

        # --- Fixed layout zones (px) ---
        HEADER_H  = PAGE_HEADER_H   # styled header bar
        TOP_PAD   = 8    # space above day name
        DAY_H     = 58   # zone for large day-name text
        GAP1      = 6    # gap: day name → icon
        ICON_H    = 140  # zone for weather icon glyph / PIL drawing
        GAP2      = 6    # gap: icon → date
        DATE_H    = 24   # zone for date number
        GAP3      = 4    # gap: date → separator
        SEP_H     = 1    # separator line
        GAP4      = 4    # gap: separator → high temp
        HIGH_H    = 46   # zone for high temperature
        GAP5      = 4    # gap: high → low
        LOW_H     = 28   # zone for low temperature
        GAP6      = 4    # gap: low → precip
        PRECIP_H  = 18   # zone for precipitation (only drawn when non-zero)
        BOT_PAD   = 8    # space below last row

        col_content_h = (
            TOP_PAD + DAY_H + GAP1 + ICON_H + GAP2
            + DATE_H + GAP3 + SEP_H + GAP4
            + HIGH_H + GAP5 + LOW_H + GAP6 + PRECIP_H + BOT_PAD
        )

        # Fonts
        header_font = self._load_font(PAGE_HEADER_FONT_SIZE)
        n_days      = len(self._days)
        col_w       = width // n_days
        day_font    = self._load_day_font(col_w)
        date_font   = self._load_font(18)
        high_font   = self._load_font(30)
        low_font    = self._load_font(20)
        precip_font = self._load_font(14)

        # Icon font (Weather Icons TTF); None triggers PIL fallback
        # Cap to column width minus 8px padding per side so glyphs stay inside their column
        ICON_FONT_SIZE = min(130, col_w - 16)
        icon_font = self._load_icon_font(ICON_FONT_SIZE)

        # --- Header ---
        draw_page_header(draw, width, "7 Day Forecast", header_font, HEADER_H)

        body_top = HEADER_H + 1
        body_h   = height - body_top

        # Vertically centre the content block if shorter than the body area
        v_offset = max((body_h - col_content_h) // 2, 0)

        # Fallback PIL icon size fits in the icon zone and column width
        pil_icon_size = min(ICON_H - 10, col_w - 20)

        for i, day in enumerate(self._days):
            x0 = i * col_w
            x1 = x0 + col_w
            cx = (x0 + x1) // 2

            # Vertical divider between columns (not before the first)
            if i > 0:
                draw.line([(x0, body_top + 6), (x0, height - 6)], fill=0, width=1)

            y = body_top + v_offset

            # Today indicator — thin bar at the very top of today's column
            # (replaces the previous white-on-black full-column inversion)
            if i == 0:
                draw.rectangle([(x0, y), (x1 - 1, y + 2)], fill=0)

            y += TOP_PAD

            # Day label ("MON", "TUE", …) — auto-fit large bold font
            dtxt = day["day"].upper()
            dw, dh = self._get_text_size(draw, dtxt, day_font)
            draw.text((cx - dw // 2, y + (DAY_H - dh) // 2), dtxt, font=day_font, fill=0)
            y += DAY_H + GAP1

            # Weather icon — font glyph preferred; PIL geometry as fallback
            icon_type = day["icon"]
            icon_cy   = y + ICON_H // 2
            if icon_font is not None:
                glyph = chr(_WMO_GLYPH.get(icon_type, _WMO_GLYPH["cloud"]))
                gw, gh = self._get_text_size(draw, glyph, icon_font)
                draw.text((cx - gw // 2, icon_cy - gh // 2), glyph, font=icon_font, fill=0)
            else:
                _draw_icon(draw, icon_type, cx, icon_cy, pil_icon_size)
            y += ICON_H + GAP2

            # Date number ("1", "15", …) — small, below icon
            num = day["dt"].strftime("%d").lstrip("0") or "1"
            nw, nh = self._get_text_size(draw, num, date_font)
            draw.text((cx - nw // 2, y + (DATE_H - nh) // 2), num, font=date_font, fill=0)
            y += DATE_H + GAP3

            # Separator between date and temperatures
            draw.line([(x0 + 8, y), (x1 - 8, y)], fill=0, width=1)
            y += SEP_H + GAP4

            # High temperature (primary reading — largest font in the temp section)
            htxt = self._fmt_temp(day["high"])
            hw2, hh2 = self._get_text_size(draw, htxt, high_font)
            draw.text((cx - hw2 // 2, y + (HIGH_H - hh2) // 2), htxt, font=high_font, fill=0)
            y += HIGH_H + GAP5

            # Low temperature — smaller font, visually subordinate
            ltxt = self._fmt_temp(day["low"])
            lw, lh = self._get_text_size(draw, ltxt, low_font)
            draw.text((cx - lw // 2, y + (LOW_H - lh) // 2), ltxt, font=low_font, fill=0)
            y += LOW_H + GAP6

            # Precipitation (only when non-zero)
            pstr = self._fmt_precip(day["precip"])
            if pstr:
                pw, ph = self._get_text_size(draw, pstr, precip_font)
                draw.text(
                    (cx - pw // 2, y + max((PRECIP_H - ph) // 2, 2)),
                    pstr, font=precip_font, fill=0,
                )

        return image
