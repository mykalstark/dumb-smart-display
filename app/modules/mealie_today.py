# modules/mealie_today.py

import datetime
import logging
from typing import Optional, Dict, Any, List

import requests  # make sure this is installed in your venv / system

log = logging.getLogger(__name__)


class Module:
    """
    Module that shows today's planned dinner from Mealie.
    Expects the /api/households/mealplans/today endpoint to return a list
    of entries like the one you showed, with entryType and recipe.name.
    """

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        """
        config:
            {
              "base_url": "http://192.168.xx.yy:9000",
              "api_token": "xxx",
              "refresh_seconds": 3600
            }
        fonts:
            dict of PIL.ImageFont instances, e.g. fonts["large"], fonts["small"]
        """
        self.base_url = config["base_url"].rstrip("/")
        self.api_token = config["api_token"]
        self.refresh_seconds = config.get("refresh_seconds", 3600)

        self.fonts = fonts
        self.last_fetch: Optional[datetime.datetime] = None
        self.meal_name: str = "No dinner planned"

    # ------------------------
    # Internal helpers
    # ------------------------
    def _fetch_today_mealplan(self) -> Optional[List[Dict[str, Any]]]:
        url = f"{self.base_url}/api/households/mealplans/today"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            log.warning("Failed to fetch Mealie meal plan: %s", e)
            return None

        try:
            data = resp.json()
        except ValueError:
            log.warning("Invalid JSON from Mealie at %s", url)
            return None

        if not isinstance(data, list):
            log.warning("Unexpected mealplan payload type: %s", type(data))
            return None

        return data

    def _extract_dinner_name(self, entries: List[Dict[str, Any]]) -> Optional[str]:
        """
        Given the list response from /mealplans/today, return the dinner recipe name.
        """
        for entry in entries:
            if entry.get("entryType") != "dinner":
                continue

            recipe = entry.get("recipe") or {}
            name = recipe.get("name")
            if name:
                return name

        return None

    # ------------------------
    # Public module API
    # ------------------------
    def update(self, now: Optional[datetime.datetime] = None) -> None:
        """
        Called by the main loop to refresh data. Respects refresh_seconds.
        """
        if now is None:
            now = datetime.datetime.utcnow()

        if self.last_fetch and (now - self.last_fetch).total_seconds() < self.refresh_seconds:
            return

        entries = self._fetch_today_mealplan()
        if not entries:
            self.meal_name = "No dinner planned"
            self.last_fetch = now
            return

        dinner_name = self._extract_dinner_name(entries)
        if dinner_name:
            self.meal_name = dinner_name
        else:
            self.meal_name = "No dinner planned"

        self.last_fetch = now

    def render(self, draw, width: int, height: int) -> None:
        """
        Render onto the e-ink display.

        draw: PIL.ImageDraw.Draw
        width, height: display dimensions in pixels
        """
        title_font = self.fonts.get("large") or self.fonts.get("default")
        body_font = self.fonts.get("small") or self.fonts.get("default")

        title = "Today's Dinner"
        meal = self.meal_name

        # Simple centered layout
        title_w, title_h = draw.textsize(title, font=title_font)
        meal_w, meal_h = draw.textsize(meal, font=body_font)

        title_x = (width - title_w) // 2
        title_y = 10

        meal_x = (width - meal_w) // 2
        meal_y = title_y + title_h + 10

        draw.text((title_x, title_y), title, font=title_font, fill=0)
        draw.text((meal_x, meal_y), meal, font=body_font, fill=0)