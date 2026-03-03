"""7-day weather forecast module using Open-Meteo (free, no API key)."""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WMO weather code → icon type mapping
# https://open-meteo.com/en/docs#weathervariables
# ---------------------------------------------------------------------------
def _wmo_to_icon(code: int) -> str:
    if code == 0:
        return "sun"
    if code == 1:
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


# ---------------------------------------------------------------------------
# Geometric icon drawing helpers
# All icons are drawn centred on (cx, cy) within a bounding box of ~size px.
# ---------------------------------------------------------------------------

def _draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    r = size // 4
    # Centre circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=2)
    # 8 rays
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
    # Main body — wide oval
    bx0, by0, bx1, by1 = cx - w // 2, cy - h // 4, cx + w // 2, cy + h // 4
    draw.ellipse([bx0, by0, bx1, by1], outline=0, width=2, fill=fill)
    # Left bump
    lbr = h // 3
    draw.ellipse(
        [cx - w // 3 - lbr, cy - h // 4 - lbr, cx - w // 3 + lbr, cy - h // 4 + lbr],
        outline=0, width=2, fill=fill,
    )
    # Centre-left bump (tallest)
    cbr = int(h * 0.42)
    draw.ellipse(
        [cx - cbr, cy - h // 4 - cbr, cx + cbr, cy - h // 4 + cbr],
        outline=0, width=2, fill=fill,
    )
    # Right bump
    rbr = h // 4
    draw.ellipse(
        [cx + w // 5 - rbr, cy - h // 4 - rbr, cx + w // 5 + rbr, cy - h // 4 + rbr],
        outline=0, width=2, fill=fill,
    )


def _draw_cloud(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    _draw_cloud_shape(draw, cx, cy, int(size * 0.9), size // 2)


def _draw_sun_cloud(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    # Small sun offset upper-left, cloud lower-right
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
    # Cloud slightly lower-right, covering part of the sun
    cloud_cx = cx + size // 8
    cloud_cy = cy + size // 8
    _draw_cloud_shape(draw, cloud_cx, cloud_cy, int(size * 0.65), size // 3)


def _draw_rain(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, *, heavy: bool = False) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 7
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.85), cloud_h)
    # Rain drops: 3 diagonal lines below the cloud
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
    # Light drizzle dots
    drop_top = cloud_top_cy + cloud_h // 2 + 8
    for i in range(3):
        x = cx - size // 4 + i * (size // 4)
        draw.ellipse([x - 2, drop_top, x + 2, drop_top + 4], fill=0)
        draw.ellipse([x - 2, drop_top + 10, x + 2, drop_top + 14], fill=0)


def _draw_snow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    cloud_h = size // 3
    cloud_top_cy = cy - size // 8
    _draw_cloud_shape(draw, cx, cloud_top_cy, int(size * 0.85), cloud_h)
    # Snow dots (small asterisks / dots)
    dot_top = cloud_top_cy + cloud_h // 2 + 8
    for i in range(3):
        x = cx - size // 3 + i * (size // 3) + size // 6
        y = dot_top
        r = 3
        # Six-pointed star shape: 3 lines through centre
        for angle_deg in (0, 60, 120):
            ang = math.radians(angle_deg)
            draw.line(
                [(x - r * math.cos(ang), y - r * math.sin(ang)),
                 (x + r * math.cos(ang), y + r * math.sin(ang))],
                fill=0, width=2,
            )
        # Second row
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
    # Lightning bolt below cloud
    bolt_top = cloud_top_cy + cloud_h // 2 + 4
    bolt_w = size // 5
    bolt_h = size // 3
    # Zig-zag: top-right → middle-left → bottom-right
    pts = [
        (cx + bolt_w // 2, bolt_top),
        (cx, bolt_top + bolt_h // 2),
        (cx + bolt_w // 3, bolt_top + bolt_h // 2),
        (cx - bolt_w // 2, bolt_top + bolt_h),
    ]
    draw.line(pts, fill=255, width=3)  # white on filled cloud bg


def _draw_fog(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    # Three horizontal rounded lines
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
        unit = "in" if self._unit_is_fahrenheit() else "mm"
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

    # ------------------------------------------------------------------
    # Data fetching
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

        # Fixed, legible font sizes — previously scaled proportionally to row height
        # which produced ~58px high / ~47px low on a 480px display.
        header_font = self._load_font(18)
        day_font    = self._load_font(15)
        date_font   = self._load_font(11)
        high_font   = self._load_font(20)
        low_font    = self._load_font(15)
        precip_font = self._load_font(11)

        # --- Header ---
        HEADER_H = 34
        hdr_text = self.location_name
        hw, hh = self._get_text_size(draw, hdr_text, header_font)
        draw.text(((width - hw) // 2, (HEADER_H - hh) // 2), hdr_text, font=header_font, fill=0)
        draw.line([(0, HEADER_H), (width, HEADER_H)], fill=0, width=1)

        n_days = len(self._days)
        col_w = width // n_days
        body_top = HEADER_H + 1
        body_h = height - body_top

        # Row heights — proportional with min/max caps so they scale sensibly on
        # any display size while keeping text from dominating the layout.
        day_h     = min(max(int(body_h * 0.07), 20), 32)
        date_h    = min(max(int(body_h * 0.05), 14), 22)
        icon_zone = min(max(int(body_h * 0.43), 70), 200)
        sep_h     = 8   # space consumed by separator line
        high_h    = min(max(int(body_h * 0.08), 22), 32)
        low_h     = min(max(int(body_h * 0.07), 18), 26)
        precip_h  = min(max(int(body_h * 0.06), 14), 22)
        top_pad   = 8

        content_h = top_pad + day_h + date_h + icon_zone + sep_h + high_h + low_h + precip_h

        # Vertically centre the content block within each column body
        v_offset = max((body_h - content_h) // 2, 0)

        # Icon fits within the zone height and the column width
        icon_size = min(icon_zone - 10, col_w - 20)

        for i, day in enumerate(self._days):
            x0 = i * col_w
            x1 = x0 + col_w
            cx = (x0 + x1) // 2

            # Vertical divider between columns (not before the first)
            if i > 0:
                draw.line([(x0, body_top + 6), (x0, height - 6)], fill=0, width=1)

            y = body_top + v_offset + top_pad

            # Day label ("MON", "TUE", …)
            dtxt = day["day"].upper()
            dw, dh = self._get_text_size(draw, dtxt, day_font)
            draw.text((cx - dw // 2, y + (day_h - dh) // 2), dtxt, font=day_font, fill=0)
            y += day_h

            # Date number ("1", "15", …) — small, below the day label
            num = day["dt"].strftime("%d").lstrip("0") or "1"
            nw, nh = self._get_text_size(draw, num, date_font)
            draw.text((cx - nw // 2, y + (date_h - nh) // 2), num, font=date_font, fill=0)
            y += date_h

            # Weather icon centred within icon_zone
            _draw_icon(draw, day["icon"], cx, y + icon_zone // 2, icon_size)
            y += icon_zone

            # Thin separator between icon and temperature rows
            draw.line([(x0 + 8, y + 2), (x1 - 8, y + 2)], fill=0, width=1)
            y += sep_h

            # High temperature — larger font for primary reading
            htxt = self._fmt_temp(day["high"])
            hw2, hh2 = self._get_text_size(draw, htxt, high_font)
            draw.text((cx - hw2 // 2, y + (high_h - hh2) // 2), htxt, font=high_font, fill=0)
            y += high_h

            # Low temperature — smaller font, visually subordinate
            ltxt = self._fmt_temp(day["low"])
            lw, lh = self._get_text_size(draw, ltxt, low_font)
            draw.text((cx - lw // 2, y + (low_h - lh) // 2), ltxt, font=low_font, fill=0)
            y += low_h

            # Precipitation amount (only when non-zero)
            pstr = self._fmt_precip(day["precip"])
            if pstr:
                pw, ph = self._get_text_size(draw, pstr, precip_font)
                draw.text(
                    (cx - pw // 2, y + max((precip_h - ph) // 2, 2)),
                    pstr, font=precip_font, fill=0,
                )

        # Highlight today (always index 0 in Open-Meteo response) by inverting
        # the column body — white-on-black stands out cleanly on e-ink.
        today_crop = image.crop((0, body_top, col_w, height))
        today_inv = today_crop.convert("L").point(lambda x: 255 - x).convert("1")
        image.paste(today_inv, (0, body_top))

        return image
