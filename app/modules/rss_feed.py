"""RSS/Atom feed headlines module."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import OUTER_PAD, PAGE_HEADER_H, draw_page_header, fit_header_font

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
        self._items_per_page: int = 4  # updated dynamically at render time
        self._last_fetch: Optional[datetime] = None
        self._last_updated: Optional[datetime] = None
        self._error: Optional[str] = None

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
        except Exception as exc:
            log.warning("RSS fetch failed for %s: %s", self.feed_url, exc)
            self._error = "Feed unavailable"

        self._last_fetch = datetime.now()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _total_pages(self) -> int:
        if not self._items or self._items_per_page <= 0:
            return 0
        return max(1, -(-len(self._items) // self._items_per_page))  # ceiling div

    def _draw_centered(self, draw: ImageDraw.ImageDraw, width: int, height: int, text: str) -> None:
        font = self.fonts.get("default")
        tw, th = self._get_text_size(draw, text, font)
        draw.text(((width - tw) // 2, (height - th) // 2), text, font=font, fill=0)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
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

        padding = OUTER_PAD
        body_font = self.fonts.get("default")
        small_font = self.fonts.get("small", body_font)

        # --- Header (pill style matching home screen) ---
        feed_title = self._feed_title
        draw_page_header(draw, width, feed_title, fit_header_font(draw, feed_title, width))

        # --- Footer ---
        updated_str = ""
        if self._last_updated:
            updated_str = f"Updated {self._last_updated.strftime(self.time_format)}"
        total_pages = self._total_pages()
        page_str = f"Page {self._page + 1} / {total_pages}" if total_pages > 1 else ""
        footer_parts = [p for p in [page_str, updated_str] if p]
        footer_text = "  •  ".join(footer_parts)
        _, fh = self._get_text_size(draw, footer_text or "X", small_font)
        footer_y = height - padding - fh
        if footer_text:
            fw, _ = self._get_text_size(draw, footer_text, small_font)
            draw.text(((width - fw) // 2, footer_y), footer_text, font=small_font, fill=0)

        # --- Body ---
        body_top = PAGE_HEADER_H + padding
        body_bottom = footer_y - 8
        body_h = body_bottom - body_top
        body_w = width - padding * 2

        # Estimate how many items fit (use body font height + spacing)
        _, line_h = self._get_text_size(draw, "Ag", body_font)
        item_h = line_h + 8  # line height + spacing
        self._items_per_page = max(1, body_h // item_h)

        # Clamp page
        total_pages = self._total_pages()
        if total_pages > 0:
            self._page = self._page % total_pages

        start = self._page * self._items_per_page
        page_items = self._items[start: start + self._items_per_page]

        y = body_top
        for i, item in enumerate(page_items):
            global_idx = start + i + 1
            prefix = f"{global_idx}. "
            title = item["title"]

            # Truncate title to fit in one line with prefix
            full_line = prefix + title
            while full_line:
                lw, _ = self._get_text_size(draw, full_line, body_font)
                if lw <= body_w:
                    break
                # Trim title one char at a time
                if len(title) > 1:
                    title = title[:-2] + "…"
                    full_line = prefix + title
                else:
                    break

            draw.text((padding, y), full_line, font=body_font, fill=0)
            y += item_h
            if y >= body_bottom:
                break

        return image
