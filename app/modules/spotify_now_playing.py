"""Spotify Now Playing module — shows the currently playing track."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import requests
from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    LINE_SPACING, CARD_RADIUS, draw_text_block, draw_message, page_body,
)

log = logging.getLogger(__name__)

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"


class Module(BaseDisplayModule):
    name = "spotify_now_playing"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        self.client_id: str = self.config.get("client_id", "")
        self.client_secret: str = self.config.get("client_secret", "")
        self.refresh_token: str = self.config.get("refresh_token", "")
        self.refresh_seconds: int = int(self.config.get("refresh_seconds", 10))
        self.time_format: str = self.config.get("time_format", "%H:%M")

        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

        self._track: Optional[str] = None
        self._artist: Optional[str] = None
        self._album: Optional[str] = None
        self._is_playing: bool = False
        self._last_fetch: Optional[datetime] = None
        self._last_updated: Optional[datetime] = None
        self._error: Optional[str] = None

        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------
    def _credentials_configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.refresh_token
            and self.client_id != "CHANGE_ME"
            and self.client_secret != "CHANGE_ME"
            and self.refresh_token != "CHANGE_ME"
        )

    def _ensure_token(self) -> None:
        if self._access_token and self._token_expiry and datetime.now() < self._token_expiry:
            return

        if not self._credentials_configured():
            raise RuntimeError("Spotify credentials not configured")

        creds = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(creds.encode()).decode()

        resp = self._session.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()

        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        # Subtract a 60-second buffer to avoid using a nearly-expired token
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def is_empty(self) -> bool:
        return self._last_updated is not None and not self._error and self._track is None

    def tick(self) -> None:
        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch).total_seconds() < self.refresh_seconds:
            return
        self._fetch_now_playing()

    def handle_button(self, event: str) -> None:
        pass  # Display-only

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    def _fetch_now_playing(self) -> None:
        self._last_fetch = datetime.now()

        if not self._credentials_configured():
            self._error = "Spotify not configured"
            return

        try:
            self._ensure_token()
        except Exception as exc:
            log.warning("Spotify token error: %s", exc)
            self._error = "Auth failed — check credentials"
            return

        try:
            resp = self._session.get(
                _NOW_PLAYING_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=8,
            )
        except Exception as exc:
            log.warning("Spotify request failed: %s", exc)
            self._error = "Spotify unavailable"
            return

        if resp.status_code == 204:
            # No content — nothing playing
            self._track = None
            self._artist = None
            self._album = None
            self._is_playing = False
            self._error = None
            self._last_updated = datetime.now()
            return

        if resp.status_code == 401:
            # Token expired mid-session — force re-fetch next tick
            self._access_token = None
            self._token_expiry = None
            self._error = "Token expired — will retry"
            return

        if not resp.ok:
            log.warning("Spotify API error: %s", resp.status_code)
            self._error = f"API error {resp.status_code}"
            return

        try:
            data = resp.json()
        except Exception:
            self._error = "Bad response from Spotify"
            return

        item = data.get("item")
        if not item:
            self._track = None
            self._artist = None
            self._album = None
            self._is_playing = False
            self._error = None
            self._last_updated = datetime.now()
            return

        self._track = item.get("name") or "Unknown track"
        artists: List[Dict] = item.get("artists") or []
        self._artist = ", ".join(a.get("name", "") for a in artists if a.get("name")) or "Unknown artist"
        album_info = item.get("album") or {}
        self._album = album_info.get("name") or ""
        self._is_playing = bool(data.get("is_playing", False))
        self._error = None
        self._last_updated = datetime.now()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _draw_centered(self, draw, width, height, text):
        draw_message(draw, width, height, text, self.fonts.get("default"))

    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self._fetch_now_playing()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        if self._error:
            self._draw_centered(draw, width, height, self._error)
            return image

        title = "Now Playing" if self._track and self._is_playing else "Spotify"
        x0, y0, x1, y1 = page_body(draw, width, height, title)
        default_font = self.fonts.get("default")
        small_font = self.fonts.get("small", default_font)
        footer_h = min(28, (y1 - y0) // 6)
        body_bottom = y1 - footer_h - LINE_SPACING
        if self._track is None:
            draw_text_block(draw, (x0, y0, x1, body_bottom), "Nothing playing", default_font)
        else:
            body_h = body_bottom - y0
            badge_h = min(36, body_h // 5)
            badge_w = min(x1 - x0, 160)
            badge_x = (width - badge_w) // 2
            draw.rounded_rectangle([(badge_x, y0), (badge_x + badge_w - 1, y0 + badge_h - 1)],
                                   radius=CARD_RADIUS, outline=0, width=2,
                                   fill=0 if self._is_playing else None)
            draw_text_block(draw, (badge_x + 6, y0 + 4, badge_x + badge_w - 6, y0 + badge_h - 4),
                            "Now Playing" if self._is_playing else "Paused", small_font,
                            255 if self._is_playing else 0)
            track_top = y0 + badge_h + LINE_SPACING
            remaining = body_bottom - track_top
            track_bottom = track_top + remaining * 55 // 100
            artist_bottom = track_bottom + remaining * 27 // 100
            draw_text_block(draw, (x0, track_top, x1, track_bottom), self._track,
                            self.fonts.get("large", default_font), max_lines=2,
                            min_size=min(28, max(14, (x1 - x0) // 20)))
            draw_text_block(draw, (x0, track_bottom + LINE_SPACING, x1, artist_bottom),
                            self._artist or "", default_font, min_size=min(18, max(12, (x1 - x0) // 20)))
            draw_text_block(draw, (x0, artist_bottom + LINE_SPACING, x1, body_bottom),
                            self._album or "", small_font)
        if self._last_updated:
            label = "Updated" if self._track else "Last checked"
            draw_text_block(draw, (x0, y1 - footer_h, x1, y1),
                            f"{label} {self._last_updated.strftime(self.time_format)}", small_font)
        return image
