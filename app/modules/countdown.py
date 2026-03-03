"""Countdown module — displays days remaining to one or more named events."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset

log = logging.getLogger(__name__)


class Module(BaseDisplayModule):
    name = "countdown"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        self.show_past_days: int = int(self.config.get("show_past_days", 7))

        self._events: List[Dict[str, Any]] = self._parse_events(
            self.config.get("events") or []
        )
        self._active_index: int = 0

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------
    def _parse_events(self, raw: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            return []

        parsed = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "Event")
            raw_date = item.get("date")
            if not raw_date:
                continue
            try:
                event_date = date.fromisoformat(str(raw_date))
            except ValueError:
                log.warning("countdown: Could not parse date '%s' for event '%s'", raw_date, name)
                continue
            parsed.append({"name": name, "date": event_date})

        return parsed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def tick(self) -> None:
        # Pure date math — no I/O needed.
        pass

    def handle_button(self, event: str) -> None:
        visible = self._visible_events()
        if not visible:
            return
        if event == "next":
            self._active_index = (self._active_index + 1) % len(visible)
        elif event in {"back", "prev"}:
            self._active_index = (self._active_index - 1) % len(visible)

    def refresh_interval(self) -> Optional[int]:
        return 60

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)  # full

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _visible_events(self) -> List[Dict[str, Any]]:
        today = date.today()
        result = []
        for ev in self._events:
            delta = (ev["date"] - today).days
            if delta >= 0 or abs(delta) <= self.show_past_days:
                result.append(ev)
        return result

    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _load_font(self, size: int) -> Any:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return self.fonts.get("large", self.fonts.get("default"))

    def _fit_number_font(self, draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int) -> Any:
        """Return the largest font that fits the number string in the given box."""
        for size in range(280, 24, -4):
            font = self._load_font(size)
            w, h = self._get_text_size(draw, text, font)
            if w <= max_w and h <= max_h:
                return font
        return self._load_font(24)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        visible = self._visible_events()

        if not self._events:
            self._draw_centered(draw, width, height, "No events configured")
            return image

        if not visible:
            self._draw_centered(draw, width, height, "No upcoming events")
            return image

        # Clamp active index in case events changed
        self._active_index = self._active_index % len(visible)
        event = visible[self._active_index]
        today = date.today()
        delta = (event["date"] - today).days

        if delta == 0:
            count_str = "TODAY"
            label_str = event["name"] + "!"
        elif delta > 0:
            count_str = str(delta)
            label_str = "days to go"
        else:
            count_str = str(abs(delta))
            label_str = "days ago"

        padding = 28
        inner_w = width - padding * 2
        inner_h = height - padding * 2

        # Reserve space for name (top) and label (bottom)
        name_font = self.fonts.get("large", self.fonts.get("default"))
        name_w, name_h = self._get_text_size(draw, event["name"], name_font)

        label_font = self.fonts.get("default")
        label_w, label_h = self._get_text_size(draw, label_str, label_font)

        # Pagination indicator at bottom if multiple events
        pagination_h = 0
        if len(visible) > 1:
            pag_font = self.fonts.get("small", label_font)
            pag_str = f"{self._active_index + 1} / {len(visible)}"
            _, pagination_h = self._get_text_size(draw, pag_str, pag_font)
            pagination_h += 10

        number_max_h = inner_h - name_h - 18 - label_h - 16 - pagination_h
        number_max_w = inner_w

        # Draw event name at top, centered
        name_x = (width - name_w) // 2
        name_y = padding
        draw.text((name_x, name_y), event["name"], font=name_font, fill=0)

        # Divider line under name
        line_y = name_y + name_h + 8
        draw.line([(padding, line_y), (width - padding, line_y)], fill=0, width=1)

        # Big number centered in remaining space
        number_area_top = line_y + 10
        if delta == 0:
            # "TODAY" — use large font, no huge number
            today_font = self._load_font(96)
            tw, th = self._get_text_size(draw, count_str, today_font)
            tx = (width - tw) // 2
            ty = number_area_top + (number_max_h - th) // 2
            draw.text((tx, ty), count_str, font=today_font, fill=0)
        else:
            number_font = self._fit_number_font(draw, count_str, number_max_w, number_max_h)
            nw, nh = self._get_text_size(draw, count_str, number_font)
            nx = (width - nw) // 2
            ny = number_area_top + (number_max_h - nh) // 2
            draw.text((nx, ny), count_str, font=number_font, fill=0)

        # Label below number
        label_x = (width - label_w) // 2
        label_y = height - padding - pagination_h - label_h - 4
        draw.text((label_x, label_y), label_str, font=label_font, fill=0)

        # Pagination indicator
        if len(visible) > 1:
            pag_font = self.fonts.get("small", label_font)
            pag_str = f"{self._active_index + 1} / {len(visible)}"
            pw, ph = self._get_text_size(draw, pag_str, pag_font)
            draw.text(((width - pw) // 2, height - padding - ph), pag_str, font=pag_font, fill=0)

        return image

    def _draw_centered(self, draw: ImageDraw.ImageDraw, width: int, height: int, text: str) -> None:
        font = self.fonts.get("default")
        tw, th = self._get_text_size(draw, text, font)
        draw.text(((width - tw) // 2, (height - th) // 2), text, font=font, fill=0)
