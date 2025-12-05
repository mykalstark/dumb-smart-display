# app/modules/mealie_today.py

import datetime
import logging
import textwrap
from typing import Optional, Dict, Any, List, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

class Module:
    name = "mealie_today"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_token = config.get("api_token", "")
        self.refresh_seconds = config.get("refresh_seconds", 3600)
        self.target_eat_time = config.get("target_eat_time", "18:30")

        self.fonts = fonts
        self.last_fetch: Optional[datetime.datetime] = None
        self.meal_details: Dict[str, Optional[Any]] = {
            "name": "No dinner planned",
            "prep": None,
            "cook": None,
            "total": None,
        }

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

    def _parse_duration_minutes(self, value: Any) -> Optional[int]:
        """
        Convert various time formats to minutes.

        Mealie may return times as integers (minutes), strings like "45",
        "45m", or ISO8601 durations like "PT1H15M". We handle the common
        variations and fall back to None when we can't parse.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return int(value)

        if isinstance(value, str):
            stripped = value.strip().upper()
            # Simple numeric string ("45")
            if stripped.isdigit():
                return int(stripped)

            # ISO8601 duration (PT#H#M#S)
            if stripped.startswith("PT"):
                hours = minutes = seconds = 0
                num = ""
                for char in stripped[2:]:
                    if char.isdigit():
                        num += char
                        continue
                    if char == "H":
                        hours = int(num or 0)
                        num = ""
                    elif char == "M":
                        minutes = int(num or 0)
                        num = ""
                    elif char == "S":
                        seconds = int(num or 0)
                        num = ""
                return hours * 60 + minutes + (1 if seconds else 0)

            # Formats like "45M", "1H 15M", "45 min"
            total_minutes = 0
            segments = stripped.replace("MIN", "M").replace("HOUR", "H").split()
            for segment in segments:
                num = "".join(ch for ch in segment if ch.isdigit())
                if not num:
                    continue
                if segment.endswith("H"):
                    total_minutes += int(num) * 60
                else:
                    total_minutes += int(num)
            return total_minutes or None

        return None

    def _extract_dinner_details(self, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Optional[Any]]]:
        if not isinstance(entries, list):
            return None

        for entry in entries:
            if entry.get("entryType") == "dinner":
                recipe = entry.get("recipe") or {}
                prep = self._parse_duration_minutes(recipe.get("prepTime"))
                cook = self._parse_duration_minutes(
                    recipe.get("performTime") or recipe.get("cookTime")
                )
                total = self._parse_duration_minutes(recipe.get("totalTime"))

                if total is None and prep is not None and cook is not None:
                    total = prep + cook

                return {
                    "name": recipe.get("name") or entry.get("title"),
                    "prep": prep,
                    "cook": cook,
                    "total": total,
                }
        return None

    def tick(self) -> None:
        """Background task to fetch data occasionally."""
        now = datetime.datetime.now()

        if self.last_fetch is None or (now - self.last_fetch).total_seconds() > self.refresh_seconds:
            entries = self._fetch_today_mealplan()
            if entries:
                dinner = self._extract_dinner_details(entries)
                if dinner:
                    self.meal_details = {
                        "name": dinner.get("name") or "No dinner planned",
                        "prep": dinner.get("prep"),
                        "cook": dinner.get("cook"),
                        "total": dinner.get("total"),
                    }
                else:
                    self.meal_details = {
                        "name": "No dinner planned",
                        "prep": None,
                        "cook": None,
                        "total": None,
                    }
            self.last_fetch = now

    def handle_button(self, event: str) -> None:
        # Action handling is not yet implemented for this module.
        return

    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

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

    def _parse_target_time(self) -> datetime.time:
        """Return configured target eat time, defaulting to 18:30 when parsing fails."""
        candidates = ["%H:%M", "%I:%M %p", "%I:%M%p"]
        for fmt in candidates:
            try:
                return datetime.datetime.strptime(self.target_eat_time, fmt).time()
            except ValueError:
                continue
        return datetime.time(hour=18, minute=30)

    def _format_minutes(self, value: Optional[int]) -> str:
        if value is None:
            return "--"
        hours, minutes = divmod(int(value), 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes or not parts:
            parts.append(f"{minutes}m")
        return " ".join(parts)

    def _compute_start_time(self, total_minutes: Optional[int]) -> Optional[datetime.datetime]:
        if total_minutes is None:
            return None

        target_time = self._parse_target_time()
        today = datetime.datetime.now().date()
        target_dt = datetime.datetime.combine(today, target_time)
        return target_dt - datetime.timedelta(minutes=total_minutes)

    def _format_clock(self, dt_obj: datetime.datetime) -> str:
        return dt_obj.strftime("%I:%M %p").lstrip("0")

    # ------------------------
    # Main Render
    # ------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        # 1. Create Canvas (White Background)
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        header_height = int(height * 0.22)
        header_inset = 24
        body_padding = 32

        # 2. Draw Header Bar
        draw.rounded_rectangle(
            [
                (header_inset, header_inset),
                (width - header_inset, header_height - header_inset),
            ],
            radius=18,
            fill=0,
        )

        header_text = "Tonight's Dinner"
        header_font = self.fonts.get("large", self.fonts.get("default"))
        hw, hh = self._get_text_size(draw, header_text, header_font)
        hx = (width - hw) // 2
        hy = header_inset + ((header_height - (header_inset * 2)) - hh) // 2
        draw.text((hx, hy), header_text, font=header_font, fill=255)

        # Divider shadow effect (simple double line)
        draw.line(
            [(header_inset, header_height), (width - header_inset, header_height)],
            fill=0,
            width=2,
        )
        draw.line(
            [(header_inset, header_height + 4), (width - header_inset, header_height + 4)],
            fill=0,
            width=1,
        )

        # 3. Meal Name Section
        meal_text = str(self.meal_details.get("name") or "No dinner planned")
        meal_font = self.fonts.get("large", self.fonts.get("default"))
        body_y_start = header_height + 12
        max_text_width = width - (body_padding * 2)
        lines = self._wrap_text(draw, meal_text, meal_font, max_text_width)

        current_y = body_y_start + 12
        for line in lines:
            lw, lh = self._get_text_size(draw, line, meal_font)
            lx = (width - lw) // 2
            draw.text((lx, current_y), line, font=meal_font, fill=0)
            current_y += lh + 6

        # 4. Time Details Card
        card_top = current_y + 10
        card_height = 170
        card_left = body_padding
        card_right = width - body_padding
        card_bottom = min(card_top + card_height, height - body_padding)

        draw.rounded_rectangle(
            [(card_left, card_top), (card_right, card_bottom)],
            radius=16,
            outline=0,
            width=2,
        )

        label_font = self.fonts.get("default")
        value_font = self.fonts.get("default")

        prep_text = self._format_minutes(self.meal_details.get("prep"))
        cook_text = self._format_minutes(self.meal_details.get("cook"))
        total_text = self._format_minutes(self.meal_details.get("total"))

        col_width = (card_right - card_left) // 3
        col_centers = [card_left + col_width * i + col_width // 2 for i in range(3)]
        labels = ["Prep", "Cook", "Total"]
        values = [prep_text, cook_text, total_text]

        card_content_top = card_top + 24
        for idx, (label, value) in enumerate(zip(labels, values)):
            lw, lh = self._get_text_size(draw, label, label_font)
            vw, vh = self._get_text_size(draw, value, value_font)
            cx = col_centers[idx]
            draw.text((cx - lw // 2, card_content_top), label, font=label_font, fill=0)
            draw.text(
                (cx - vw // 2, card_content_top + lh + 10),
                value,
                font=value_font,
                fill=0,
            )

        # Vertical separators
        draw.line(
            [(card_left + col_width, card_top + 12), (card_left + col_width, card_bottom - 12)],
            fill=0,
            width=1,
        )
        draw.line(
            [
                (card_left + 2 * col_width, card_top + 12),
                (card_left + 2 * col_width, card_bottom - 12),
            ],
            fill=0,
            width=1,
        )

        # 5. Start Time Banner
        start_by = self._compute_start_time(self.meal_details.get("total"))
        target_time = self._parse_target_time()
        target_str = datetime.datetime.combine(datetime.date.today(), target_time)
        target_label = target_str.strftime("%I:%M %p").lstrip("0")

        if start_by:
            banner_text = f"Start by {self._format_clock(start_by)} to eat by {target_label}"
        else:
            banner_text = f"Plan to eat by {target_label}"

        banner_font = self.fonts.get("default", self.fonts.get("small"))
        bw, bh = self._get_text_size(draw, banner_text, banner_font)
        banner_padding_x = 24
        banner_padding_y = 12
        banner_left = (width - (bw + banner_padding_x * 2)) // 2
        banner_top = card_bottom + 20
        banner_right = banner_left + bw + banner_padding_x * 2
        banner_bottom = banner_top + bh + banner_padding_y * 2

        draw.rounded_rectangle(
            [(banner_left, banner_top), (banner_right, banner_bottom)],
            radius=14,
            fill=0,
        )
        draw.text(
            (banner_left + banner_padding_x, banner_top + banner_padding_y),
            banner_text,
            font=banner_font,
            fill=255,
        )

        return image
