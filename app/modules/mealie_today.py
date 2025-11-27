# app/modules/mealie_today.py

import datetime
import logging
from typing import Optional, Dict, Any, List

import requests
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

class Module:
    # Now we accept 'fonts' correctly!
    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_token = config.get("api_token", "")
        self.refresh_seconds = config.get("refresh_seconds", 3600)
        
        # Save the fonts passed from main.py
        self.fonts = fonts

        self.last_fetch: Optional[datetime.datetime] = None
        self.meal_name: str = "No dinner planned"

    def _fetch_today_mealplan(self) -> Optional[List[Dict[str, Any]]]:
        if not self.base_url or not self.api_token:
            return None
        url = f"{self.base_url}/api/households/mealplans/today"
        headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("Mealie fetch error: %s", e)
            return None

    def _extract_dinner_name(self, entries: List[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(entries, list): return None
        for entry in entries:
            if entry.get("entryType") == "dinner":
                recipe = entry.get("recipe") or {}
                if recipe.get("name"): return recipe["name"]
        return None

    def tick(self) -> None:
        now = datetime.datetime.now()
        if self.last_fetch is None or (now - self.last_fetch).total_seconds() > self.refresh_seconds:
            entries = self._fetch_today_mealplan()
            if entries:
                dinner = self._extract_dinner_name(entries)
                self.meal_name = dinner if dinner else "No dinner planned"
            self.last_fetch = now

    # Accept width/height and return an Image
    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        title = "Today's Dinner"
        meal = self.meal_name
        
        # Use the injected fonts
        title_font = self.fonts.get("large", self.fonts.get("default"))
        body_font = self.fonts.get("default")

        # Layout logic
        try:
            left, top, right, bottom = draw.textbbox((0, 0), title, font=title_font)
            title_w, title_h = right - left, bottom - top
            left, top, right, bottom = draw.textbbox((0, 0), meal, font=body_font)
            meal_w, meal_h = right - left, bottom - top
        except AttributeError:
            title_w, title_h = draw.textsize(title, font=title_font)
            meal_w, meal_h = draw.textsize(meal, font=body_font)

        title_x = (width - title_w) // 2
        title_y = (height // 2) - title_h - 20
        meal_x = (width - meal_w) // 2
        meal_y = (height // 2) + 10

        draw.text((title_x, title_y), title, font=title_font, fill=0)
        draw.text((meal_x, meal_y), meal, font=body_font, fill=0)

        return image