# app/modules/mealie_today.py

import datetime
import logging
import textwrap
from typing import Optional, Dict, Any, List, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

class Module:
    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_token = config.get("api_token", "")
        self.refresh_seconds = config.get("refresh_seconds", 3600)
        
        self.fonts = fonts
        self.last_fetch: Optional[datetime.datetime] = None
        self.meal_name: str = "No dinner planned"

    # ------------------------
    # Data Fetching Logic
    # ------------------------
    def _fetch_today_mealplan(self) -> Optional[List[Dict[str, Any]]]:
        if not self.base_url or not self.api_token:
            return None

        url = f"{self.base_url}/api/households/mealplans/today"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("Mealie fetch error: %s", e)
            return None

    def _extract_dinner_name(self, entries: List[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(entries, list):
            return None
            
        for entry in entries:
            if entry.get("entryType") == "dinner":
                recipe = entry.get("recipe") or {}
                # Return the recipe name, or the raw text if recipe is missing
                return recipe.get("name") or entry.get("title")
        return None

    def tick(self) -> None:
        """Background task to fetch data occasionally."""
        now = datetime.datetime.now()
        
        if self.last_fetch is None or (now - self.last_fetch).total_seconds() > self.refresh_seconds:
            entries = self._fetch_today_mealplan()
            if entries:
                dinner = self._extract_dinner_name(entries)
                self.meal_name = dinner if dinner else "No dinner planned"
            self.last_fetch = now

    # ------------------------
    # Render Helpers
    # ------------------------
    def _get_text_size(self, draw: ImageDraw.Draw, text: str, font: Any) -> Tuple[int, int]:
        """Compatible text size calculator for new and old Pillow versions."""
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        except AttributeError:
            return draw.textsize(text, font=font)

    def _wrap_text(self, draw: ImageDraw.Draw, text: str, font: Any, max_width: int) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        try:
            avg_width = font.size * 0.6
        except AttributeError:
            avg_width = 20
            
        approx_chars = int(max_width / avg_width)
        wrapper = textwrap.TextWrapper(width=approx_chars)
        return wrapper.wrap(text)

    # ------------------------
    # Main Render
    # ------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        # 1. Create Canvas (White Background)
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        # 2. Draw Header Bar (Top 1/4 of screen)
        # Use floor division to get approx 25% of height (e.g., 120px for 480px total)
        header_height = height // 4
        header_inset = 10
        draw.rectangle(
            [(header_inset, header_inset), (width - header_inset, header_height - header_inset)],
            fill=0,
        )

        # 3. Draw Header Text (White Text, "Large" Font)
        header_text = "TODAY'S DINNER"
        # We use the 'large' font now to make it prominent
        header_font = self.fonts.get("large", self.fonts.get("default"))

        hw, hh = self._get_text_size(draw, header_text, header_font)
        hx = (width - hw) // 2
        hy = header_inset + ((header_height - (header_inset * 2)) - hh) // 2
        draw.text((hx, hy), header_text, font=header_font, fill=255)

        # Divider to separate header and body
        draw.line(
            [(header_inset, header_height), (width - header_inset, header_height)],
            fill=0,
            width=3,
        )

        # 4. Draw Meal Name (Centered in remaining 3/4 space)
        meal_text = self.meal_name
        meal_font = self.fonts.get("large", self.fonts.get("default"))

        # Define the body area
        body_y_start = header_height
        body_height = height - header_height
        margin = 50
        max_text_width = width - (margin * 2)

        # Wrap text if needed
        lines = self._wrap_text(draw, meal_text, meal_font, max_text_width)

        # Calculate total height of the text block
        line_heights = []
        for line in lines:
            lw, lh = self._get_text_size(draw, line, meal_font)
            line_heights.append(lh)
        
        total_text_height = sum(line_heights) + (len(lines) - 1) * 10 # 10px spacing
        
        # Calculate starting Y to center the block vertically in the body
        start_y = body_y_start + (body_height - total_text_height) // 2

        # Draw each line
        current_y = start_y
        for i, line in enumerate(lines):
            lw, lh = self._get_text_size(draw, line, meal_font)
            lx = (width - lw) // 2
            draw.text((lx, current_y), line, font=meal_font, fill=0)
            current_y += line_heights[i] + 10

        return image
