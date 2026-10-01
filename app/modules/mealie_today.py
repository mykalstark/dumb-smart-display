# app/modules/mealie_today.py

import datetime
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw

from app.core.module_interface import DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, LINE_SPACING, CARD_RADIUS,
    draw_card, draw_text_block, draw_metrics, page_body, layout_slots,
)

log = logging.getLogger(__name__)

class Module:
    name = "mealie_today"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_token = config.get("api_token", "")
        self.refresh_seconds = config.get("refresh_seconds", 3600)
        self.target_eat_time = config.get("target_eat_time", "18:30")
        self.time_format = config.get("time_format", "%I:%M %p")

        self.fonts = fonts
        self.last_fetch: Optional[datetime.datetime] = None
        self._empty: bool = False
        self.meal_details: Dict[str, Optional[Any]] = {
            "name": "You Effed up, Doordash",
            "prep": None,
            "cook": None,
            "total": None,
        }

        self._default_layout = DEFAULT_LAYOUTS[0]
        self._layout_lookup = {layout.name: layout for layout in DEFAULT_LAYOUTS}

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

    def _parse_duration_minutes(
        self, value: Any, *, assume_hours_if_small: bool = False
    ) -> Optional[int]:
        """
        Convert various time formats to minutes.

        Mealie may return times as integers (minutes), strings like "45",
        "45m", or ISO8601 durations like "PT1H15M". We handle the common
        variations and fall back to None when we can't parse.

        When `assume_hours_if_small` is True, plain numeric values that are
        12 or less are treated as hours instead of minutes to account for
        Mealie's missing cook-time unit.
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            numeric_value = int(value)
            if assume_hours_if_small and numeric_value <= 12:
                return numeric_value * 60
            return numeric_value

        if isinstance(value, str):
            stripped = value.strip().upper()
            # Simple numeric string ("45")
            if stripped.isdigit():
                numeric_value = int(stripped)
                if assume_hours_if_small and numeric_value <= 12:
                    return numeric_value * 60
                return numeric_value

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
                minutes_total = hours * 60 + minutes + (1 if seconds else 0)
                if assume_hours_if_small and minutes_total <= 12:
                    minutes_total *= 60
                return minutes_total

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
            if assume_hours_if_small and total_minutes and total_minutes <= 12:
                total_minutes *= 60
            return total_minutes or None

        return None

    def _extract_dinner_details(self, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Optional[Any]]]:
        if not isinstance(entries, list):
            return None

        for entry in entries:
            if entry.get("entryType") == "dinner":
                recipe = entry.get("recipe") or {}
                prep = self._parse_duration_minutes(recipe.get("prepTime"))

                cook_source = recipe.get("cookTime") or recipe.get("performTime")
                cook = self._parse_duration_minutes(
                    cook_source,
                    assume_hours_if_small=True,
                )
                total = self._parse_duration_minutes(
                    recipe.get("totalTime"), assume_hours_if_small=True
                )

                if cook is not None:
                    prep_minutes = prep or 0

                    # When cook time is assumed to be in hours (e.g., "2" -> 2h),
                    # prefer a total that at least includes that corrected value.
                    if total is None:
                        total = prep_minutes + cook
                    elif total < cook:
                        total = prep_minutes + cook

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
            # None means fetch failure; an empty list is a valid empty plan.
            self._empty = False
            if entries is not None:
                dinner = self._extract_dinner_details(entries)
                self._empty = dinner is None
                if dinner:
                    self.meal_details = {
                        "name": dinner.get("name") or "You Effed up, Doordash",
                        "prep": dinner.get("prep"),
                        "cook": dinner.get("cook"),
                        "total": dinner.get("total"),
                    }
                else:
                    self.meal_details = {
                        "name": "You Effed up, Doordash",
                        "prep": None,
                        "cook": None,
                        "total": None,
                    }
            self.last_fetch = now

    def is_empty(self) -> bool:
        return self._empty

    def force_refresh(self) -> None:
        """Immediately fetch the latest meal plan data."""

        self.last_fetch = None
        self.tick()

    def handle_button(self, event: str) -> None:
        # Action handling is not yet implemented for this module.
        return

    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (
            self._layout_lookup.get("wide_right", DEFAULT_LAYOUTS[2]),
            self._layout_lookup.get("full", self._default_layout),
            self._layout_lookup.get("striped_rows", DEFAULT_LAYOUTS[6]),
            self._layout_lookup.get("compact_quads", DEFAULT_LAYOUTS[5]),
        )

    # ------------------------
    # Render Helpers
    # ------------------------
    def _render_full(self, width: int, height: int) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)
        x0, y0, x1, y1 = page_body(draw, width, height, "Tonight's Dinner")
        usable = y1 - y0 - 2 * COL_GAP
        title_bottom = y0 + usable * 45 // 100
        time_bottom = title_bottom + COL_GAP + usable * 35 // 100
        self._draw_title_card(draw, (x0, y0, x1, title_bottom),
                              str(self.meal_details.get("name") or "You Effed up, Doordash"), show_label=False)
        self._draw_time_card(draw, (x0, title_bottom + COL_GAP, x1, time_bottom))
        self._draw_banner(draw, (x0, time_bottom + COL_GAP, x1, y1), self._banner_text())
        return image

    def _banner_text(self):
        start_by = self._compute_start_time(self.meal_details.get("total"))
        target = datetime.datetime.combine(datetime.date.today(), self._parse_target_time())
        if start_by:
            return f"Start by {self._format_clock(start_by)} to eat by {self._format_clock(target)}"
        return f"Plan to eat by {self._format_clock(target)}"

    def _resolve_layout(self, layout_hint: Optional[Any]) -> LayoutPreset:
        if isinstance(layout_hint, LayoutPreset):
            return layout_hint
        if isinstance(layout_hint, str):
            return self._layout_lookup.get(layout_hint, self._default_layout)
        return self._default_layout

    def _layout_slots(self, layout, width, height):
        return layout_slots(layout, width, height)

    def _pick_slot(self, slots: Dict[str, Tuple[int, int, int, int]], keys: Tuple[str, ...], fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        for key in keys:
            if key in slots:
                return slots[key]
        return fallback

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

    def _compute_start_time(self, total_minutes: Optional[Any]) -> Optional[datetime.datetime]:
        parsed_total = self._parse_duration_minutes(
            total_minutes, assume_hours_if_small=True
        )

        if parsed_total is None:
            return None

        target_time = self._parse_target_time()
        today = datetime.datetime.now().date()
        target_dt = datetime.datetime.combine(today, target_time)
        return target_dt - datetime.timedelta(minutes=parsed_total)

    def _format_clock(self, dt_obj: datetime.datetime) -> str:
        result = dt_obj.strftime(self.time_format)
        # Strip leading zero from hour only for 12-hour format (01:30 PM → 1:30 PM)
        if self.time_format.startswith("%I"):
            result = result.lstrip("0")
        return result

    def _draw_title_card(self, draw, box, meal_text, *, show_label=True):
        x0, y0, x1, y1 = box
        draw_card(draw, *box)
        top = y0 + INNER_PAD
        if show_label:
            header_bottom = y0 + (y1 - y0) // 4
            draw_text_block(draw, (x0 + INNER_PAD, top, x1 - INNER_PAD, header_bottom),
                            "Tonight's Dinner", self.fonts.get("default"))
            top = header_bottom + LINE_SPACING
        draw_text_block(draw, (x0 + INNER_PAD, top, x1 - INNER_PAD, y1 - INNER_PAD),
                        meal_text, self.fonts.get("large", self.fonts.get("default")), max_lines=4,
                        min_size=min(24, max(12, (x1 - x0) // 20)))
        return y1

    def _draw_time_card(self, draw, box, invert=False):
        x0, y0, x1, y1 = box
        draw.rounded_rectangle([(x0, y0), (x1 - 1, y1 - 1)], radius=CARD_RADIUS,
                               outline=0, width=2, fill=0 if invert else None)
        draw_metrics(draw, box, ["Prep", "Cook", "Total"],
                     [self._format_minutes(self.meal_details.get(key)) for key in ("prep", "cook", "total")],
                     self.fonts.get("default"), self.fonts.get("large", self.fonts.get("default")),
                     255 if invert else 0)

    def _draw_banner(self, draw, box, text):
        x0, y0, x1, y1 = box
        draw_card(draw, *box)
        inset = min(INNER_PAD, max(4, (y1 - y0) // 6))
        draw_text_block(draw, (x0 + inset, y0 + inset, x1 - inset, y1 - inset), text,
                        self.fonts.get("default", self.fonts.get("small")), max_lines=3)

    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        layout = self._resolve_layout(kwargs.get("layout"))
        if layout.name == "full":
            return self._render_full(width, height)

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        slots = self._layout_slots(layout, width, height)
        fallback_box = (OUTER_PAD, OUTER_PAD, width - OUTER_PAD, height - OUTER_PAD)
        title_box = self._pick_slot(slots, ("main", "primary", "row1_left", "top_left", "a"), fallback_box)
        details_box = None
        footer_box = None

        for key in ("secondary", "row1_right", "top_right", "bottom_left", "bottom_right", "b", "c"):
            if key in slots:
                details_box = slots[key]
                break

        for key in ("tertiary", "row2_left", "row2_center", "row2_right", "footer_left", "footer_right", "d", "e"):
            if key in slots:
                footer_box = slots[key]
                break

        if details_box is None:
            return self._render_full(width, height)
        if (title_box[3] - title_box[1] < 100 or details_box[2] - details_box[0] < 120
                or details_box[3] - details_box[1] < 100):
            return self._render_full(width, height)
        if footer_box is None:
            # Reserve a separate region below the details instead of overlaying its text.
            x0, y0, x1, y1 = details_box
            split = y0 + (y1 - y0) * 2 // 3
            details_box = (x0, y0, x1, split - COL_GAP)
            footer_box = (x0, split, x1, y1)
        meal_text = str(self.meal_details.get("name") or "You Effed up, Doordash")
        self._draw_title_card(draw, title_box, meal_text)
        self._draw_time_card(draw, details_box, invert=layout.compact)
        self._draw_banner(draw, footer_box, self._banner_text())
        return image
