"""Spotify Now Playing module — shows the currently playing track."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import OUTER_PAD, CARD_RADIUS, PAGE_HEADER_H, draw_page_header

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
    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _draw_centered(self, draw: ImageDraw.ImageDraw, width: int, height: int, text: str) -> None:
        font = self.fonts.get("default")
        tw, th = self._get_text_size(draw, text, font)
        draw.text(((width - tw) // 2, (height - th) // 2), text, font=font, fill=0)

    def _truncate_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: Any,
        max_w: int,
    ) -> str:
        while text:
            tw, _ = self._get_text_size(draw, text, font)
            if tw <= max_w:
                return text
            if len(text) > 1:
                text = text[:-2] + "…"
            else:
                return text
        return text

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self._fetch_now_playing()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        if self._error:
            self._draw_centered(draw, width, height, self._error)
            return image

        padding = OUTER_PAD
        inner_w = width - padding * 2

        large_font = self.fonts.get("large", self.fonts.get("default"))
        default_font = self.fonts.get("default")
        small_font = self.fonts.get("small", default_font)

        # Page header — always shown so the screen is identifiable at a glance
        hdr_text = "Now Playing" if (self._track and self._is_playing) else "Spotify"
        draw_page_header(draw, width, hdr_text, default_font)
        body_top = PAGE_HEADER_H + padding

        if self._track is None:
            # Nothing playing — show a simple idle state
            msg = "Nothing playing"
            mw, mh = self._get_text_size(draw, msg, default_font)
            body_mid = body_top + (height - body_top - mh) // 2
            draw.text(((width - mw) // 2, body_mid), msg, font=default_font, fill=0)

            if self._last_updated:
                upd = f"Last checked {self._last_updated.strftime(self.time_format)}"
                uw, uh = self._get_text_size(draw, upd, small_font)
                draw.text(
                    ((width - uw) // 2, body_mid + mh + 12),
                    upd, font=small_font, fill=0,
                )
            return image

        # Status badge: "Now Playing" or "Paused"
        status_text = "Now Playing" if self._is_playing else "Paused"
        sw, sh = self._get_text_size(draw, status_text, small_font)
        badge_pad = 10
        badge_w = sw + badge_pad * 2
        badge_h = sh + badge_pad
        badge_x = (width - badge_w) // 2
        badge_y = body_top
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
            radius=CARD_RADIUS,
            fill=0 if self._is_playing else None,
            outline=0,
            width=2,
        )
        draw.text(
            (badge_x + badge_pad, badge_y + badge_pad // 2),
            status_text,
            font=small_font,
            fill=255 if self._is_playing else 0,
        )

        # Track name (large, wrapped to two lines max)
        track_y = badge_y + badge_h + 24
        track = self._track or ""
        track_font = large_font
        # Try to fit on one line; if too wide, truncate
        track_line = self._truncate_to_width(draw, track, track_font, inner_w)
        tw, th = self._get_text_size(draw, track_line, track_font)
        draw.text(((width - tw) // 2, track_y), track_line, font=track_font, fill=0)

        # Artist
        artist_y = track_y + th + 16
        artist = self._artist or ""
        artist_line = self._truncate_to_width(draw, artist, default_font, inner_w)
        aw, ah = self._get_text_size(draw, artist_line, default_font)
        draw.text(((width - aw) // 2, artist_y), artist_line, font=default_font, fill=0)

        # Album (small, below artist)
        if self._album:
            album_y = artist_y + ah + 10
            album_line = self._truncate_to_width(draw, self._album, small_font, inner_w)
            alw, alh = self._get_text_size(draw, album_line, small_font)
            draw.text(((width - alw) // 2, album_y), album_line, font=small_font, fill=0)

        # Footer: last updated
        if self._last_updated:
            upd = f"Updated {self._last_updated.strftime(self.time_format)}"
            uw, uh = self._get_text_size(draw, upd, small_font)
            draw.text(((width - uw) // 2, height - padding - uh), upd, font=small_font, fill=0)

        return image
