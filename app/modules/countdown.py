"""Countdown module — displays days remaining to one or more named events."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    LINE_SPACING, draw_text_block, draw_message, page_body,
)

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

    def _load_font(self, size: int) -> Any:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return self.fonts.get("large", self.fonts.get("default"))

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

        x0, y0, x1, y1 = page_body(draw, width, height, event["name"])
        label_h = min(40, (y1 - y0) // 5)
        pagination_h = min(28, (y1 - y0) // 6) if len(visible) > 1 else 0
        number_bottom = y1 - label_h - pagination_h - LINE_SPACING
        number_font = self._load_font(96 if delta == 0 else 280)
        draw_text_block(draw, (x0, y0, x1, number_bottom), count_str, number_font)
        draw_text_block(draw, (x0, number_bottom + LINE_SPACING, x1, y1 - pagination_h),
                        label_str, self.fonts.get("default"))
        if pagination_h:
            draw_text_block(draw, (x0, y1 - pagination_h, x1, y1),
                            f"{self._active_index + 1} / {len(visible)}",
                            self.fonts.get("small", self.fonts.get("default")))

        return image

    def _draw_centered(self, draw, width, height, text):
        draw_message(draw, width, height, text, self.fonts.get("default"))
