"""RSS/Atom feed headlines module."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    LINE_SPACING, draw_text_block, draw_message, page_body, get_text_size,
    ellipsize, wrap_text,
)

log = logging.getLogger(__name__)

try:
    import feedparser  # type: ignore
    _FEEDPARSER_AVAILABLE = True
except ImportError:
    _FEEDPARSER_AVAILABLE = False
    log.warning("feedparser not installed. RSS module will not fetch data.")


class Module(BaseDisplayModule):
    name = "rss_feed"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        self.feed_url: str = self.config.get("feed_url", "")
        self.max_items: int = int(self.config.get("max_items", 8))
        self.refresh_seconds: int = int(self.config.get("refresh_seconds", 1800))
        self.time_format: str = self.config.get("time_format", "%H:%M")

        self._items: List[Dict[str, str]] = []
        self._feed_title: str = "RSS Feed"
        self._page: int = 0
        self._page_starts: List[int] = [0]  # updated dynamically at render time
        self._last_fetch: Optional[datetime] = None
        self._last_updated: Optional[datetime] = None
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def is_empty(self) -> bool:
        return self._last_updated is not None and not self._error and not self._items

    def tick(self) -> None:
        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch).total_seconds() < self.refresh_seconds:
            return
        self._fetch()

    def handle_button(self, event: str) -> None:
        if event == "refresh":
            self._fetch()
            self._page = 0
            return

        total_pages = self._total_pages()
        if total_pages == 0:
            return

        if event == "next":
            self._page = (self._page + 1) % total_pages
        elif event in {"back", "prev"}:
            self._page = (self._page - 1) % total_pages

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    def _fetch(self) -> None:
        if not _FEEDPARSER_AVAILABLE:
            self._error = "feedparser not installed"
            return
        if not self.feed_url:
            self._error = "No feed_url configured"
            return

        try:
            parsed = feedparser.parse(self.feed_url)
            if parsed.bozo and not parsed.entries:
                self._error = f"Feed error: {parsed.bozo_exception}"
                return

            self._feed_title = (
                getattr(parsed.feed, "title", None) or self.feed_url
            )
            self._items = []
            for entry in parsed.entries[: self.max_items]:
                title = getattr(entry, "title", None) or "(No title)"
                self._items.append({"title": str(title).strip()})

            self._error = None
            self._last_updated = datetime.now()
            self._page = 0
            self._page_starts = [0]
        except Exception as exc:
            log.warning("RSS fetch failed for %s: %s", self.feed_url, exc)
            self._error = "Feed unavailable"

        self._last_fetch = datetime.now()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _total_pages(self) -> int:
        if not self._items:
            return 0
        return len(self._page_starts)

    def _draw_centered(self, draw, width, height, text):
        draw_message(draw, width, height, text, self.fonts.get("default"))

    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self.tick()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        if self._error:
            self._draw_centered(draw, width, height, self._error)
            return image

        if not self._items:
            self._draw_centered(draw, width, height, "No items in feed")
            return image

        x0, y0, x1, y1 = page_body(draw, width, height, self._feed_title)
        body_font = self.fonts.get("default")
        small_font = self.fonts.get("small", body_font)
        footer_h = min(28, (y1 - y0) // 5)
        body_bottom = y1 - footer_h - LINE_SPACING
        body_h = body_bottom - y0
        rows = []
        self._page_starts = [0]
        used_h = 0
        for i, item in enumerate(self._items):
            lines = wrap_text(draw, f"{i + 1}. {item['title']}", body_font, x1 - x0)
            line_h = max(get_text_size(draw, line, body_font)[1] for line in ["Ag", *lines])
            capacity = max(1, (body_h + LINE_SPACING) // (line_h + LINE_SPACING))
            if len(lines) > capacity:
                lines = lines[:capacity - 1] + [
                    ellipsize(draw, " ".join(lines[capacity - 1:]), body_font, x1 - x0)
                ]
            row_h = len(lines) * line_h + (len(lines) - 1) * LINE_SPACING
            if used_h + row_h > body_h and i > self._page_starts[-1]:
                self._page_starts.append(i)
                used_h = 0
            rows.append((lines, line_h))
            used_h += row_h + 2 * LINE_SPACING

        total_pages = self._total_pages()
        self._page %= total_pages
        start = self._page_starts[self._page]
        end = self._page_starts[self._page + 1] if self._page + 1 < total_pages else len(rows)
        top = y0
        for lines, line_h in rows[start:end]:
            for line in lines:
                draw_text_block(draw, (x0, top, x1, min(top + line_h, body_bottom)),
                                line, body_font, align="left",
                                min_size=getattr(body_font, "size", 12))
                top += line_h + LINE_SPACING
            top += LINE_SPACING
        parts = []
        if total_pages > 1:
            parts.append(f"Page {self._page + 1} / {total_pages}")
        if self._last_updated:
            parts.append(f"Updated {self._last_updated.strftime(self.time_format)}")
        draw_text_block(draw, (x0, y1 - footer_h, x1, y1), "  •  ".join(parts), small_font)
        return image
