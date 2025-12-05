# app/modules/mealie_today.py

import datetime
import logging
import textwrap
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import DEFAULT_LAYOUTS, LayoutPreset

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
    def _get_text_size(self, draw: ImageDraw.Draw, text: str, font: Any) -> Tuple[int, int]:
        """Compatible text size calculator for new and old Pillow versions."""
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        except AttributeError:
            return draw.textsize(text, font=font)

    def _render_full(self, width: int, height: int) -> Image.Image:
        """Classic full-screen light layout used before layout presets."""
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        header_height = int(height * 0.22)
        header_inset = 24
        body_padding = 32

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

        meal_text = str(self.meal_details.get("name") or "No dinner planned")
        meal_font = self.fonts.get("large", self.fonts.get("default"))

        hw, hh = self._get_text_size(draw, header_text, header_font)
        header_y = y0 + 12
        draw.text(((x0 + x1 - hw) // 2, header_y), header_text, font=header_font, fill=255)

        max_width = x1 - x0 - 24
        lines = self._wrap_text(draw, meal_text, meal_font, max_width)
        current_y = header_y + hh + 14
        for line in lines:
            lw, lh = self._get_text_size(draw, line, meal_font)
            draw.text(((x0 + x1 - lw) // 2, current_y), line, font=meal_font, fill=255)
            current_y += lh + 6

        card_top = current_y + 10
        card_height = 170
        card_left = body_padding
        card_right = width - body_padding
        card_bottom = min(card_top + card_height, height - body_padding)

    def _draw_time_card(self, draw: ImageDraw.Draw, box: Tuple[int, int, int, int], invert: bool = False) -> None:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        bg_fill = 0 if invert else 255
        text_fill = 255 if invert else 0

        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=16, outline=0, width=2, fill=bg_fill if invert else None)

        label_font = self.fonts.get("default")
        value_font = self.fonts.get("large", self.fonts.get("default"))

        prep_text = self._format_minutes(self.meal_details.get("prep"))
        cook_text = self._format_minutes(self.meal_details.get("cook"))
        total_text = self._format_minutes(self.meal_details.get("total"))

        col_width = (x1 - x0) // 3
        col_centers = [x0 + col_width * i + col_width // 2 for i in range(3)]
        labels = ["Prep", "Cook", "Total"]
        values = [prep_text, cook_text, total_text]

        top = y0 + 20
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
        )
        draw.text((cx + padding_x, cy + padding_y), text, font=banner_font, fill=255)

    # ------------------------
    # Main Render
    # ------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        layout = self._resolve_layout(kwargs.get("layout"))
        slots = self._layout_slots(layout, width, height)

        fallback_box = (0, 0, width, height)
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

        meal_text = str(self.meal_details.get("name") or "No dinner planned")
        bottom_of_title = self._draw_title_card(draw, title_box, meal_text)

        if details_box:
            self._draw_time_card(draw, details_box, invert=layout.compact)
        else:
            stacked_box = (title_box[0], bottom_of_title + 10, title_box[2], title_box[3])
            self._draw_time_card(draw, stacked_box)

        start_by = self._compute_start_time(self.meal_details.get("total"))
        target_time = self._parse_target_time()
        target_str = datetime.datetime.combine(datetime.date.today(), target_time)
        target_label = target_str.strftime("%I:%M %p").lstrip("0")

        if start_by:
            banner_text = f"Start by {self._format_clock(start_by)} to eat by {target_label}"
        else:
            banner_text = f"Plan to eat by {target_label}"

        banner_area = footer_box or details_box or title_box
        self._draw_banner(draw, banner_area, banner_text)

        return image

    def _resolve_layout(self, layout_hint: Optional[Any]) -> LayoutPreset:
        if isinstance(layout_hint, LayoutPreset):
            return layout_hint
        if isinstance(layout_hint, str):
            return self._layout_lookup.get(layout_hint, self._default_layout)
        return self._default_layout

    def _find_first_fit(self, columns: int, rows: int, colspan: int, rowspan: int, occupied: list[list[bool]]) -> Optional[Tuple[int, int]]:
        for row in range(rows):
            for col in range(columns):
                if row + rowspan > rows or col + colspan > columns:
                    continue
                if any(
                    occupied[r][c]
                    for r in range(row, row + rowspan)
                    for c in range(col, col + colspan)
                ):
                    continue
                for r in range(row, row + rowspan):
                    for c in range(col, col + colspan):
                        occupied[r][c] = True
                return col, row
        return None

    def _layout_slots(self, layout: LayoutPreset, width: int, height: int) -> Dict[str, Tuple[int, int, int, int]]:
        cell_w = width / layout.columns
        cell_h = height / layout.rows
        occupied = [[False for _ in range(layout.columns)] for _ in range(layout.rows)]
        slots: Dict[str, Tuple[int, int, int, int]] = {}

        for slot in layout.slots:
            start = self._find_first_fit(layout.columns, layout.rows, slot.colspan, slot.rowspan, occupied)
            if start is None:
                continue
            col, row = start
            x0 = int(round(col * cell_w))
            y0 = int(round(row * cell_h))
            x1 = int(round((col + slot.colspan) * cell_w))
            y1 = int(round((row + slot.rowspan) * cell_h))
            slots[slot.key] = (x0, y0, x1, y1)

        return slots

    def _inset_box(self, box: Tuple[int, int, int, int], padding: int) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        return x0 + padding, y0 + padding, x1 - padding, y1 - padding

    def _pick_slot(self, slots: Dict[str, Tuple[int, int, int, int]], keys: Tuple[str, ...], fallback: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        for key in keys:
            if key in slots:
                return slots[key]
        return fallback

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

    def _draw_title_card(self, draw: ImageDraw.Draw, box: Tuple[int, int, int, int], meal_text: str) -> int:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=18, outline=0, width=2)

        header_text = "Tonight's Dinner"
        header_font = self.fonts.get("large", self.fonts.get("default"))
        meal_font = self.fonts.get("large", self.fonts.get("default"))

        hw, hh = self._get_text_size(draw, header_text, header_font)
        header_y = y0 + 12
        draw.text(((x0 + x1 - hw) // 2, header_y), header_text, font=header_font, fill=0)

        max_width = x1 - x0 - 24
        lines = self._wrap_text(draw, meal_text, meal_font, max_width)
        current_y = header_y + hh + 14
        for line in lines:
            lw, lh = self._get_text_size(draw, line, meal_font)
            draw.text(((x0 + x1 - lw) // 2, current_y), line, font=meal_font, fill=0)
            current_y += lh + 6

        return current_y

    def _draw_time_card(self, draw: ImageDraw.Draw, box: Tuple[int, int, int, int], invert: bool = False) -> None:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        bg_fill = 0 if invert else None
        text_fill = 255 if invert else 0

        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=16, outline=0, width=2, fill=bg_fill)

        label_font = self.fonts.get("default")
        value_font = self.fonts.get("large", self.fonts.get("default"))

        prep_text = self._format_minutes(self.meal_details.get("prep"))
        cook_text = self._format_minutes(self.meal_details.get("cook"))
        total_text = self._format_minutes(self.meal_details.get("total"))

        col_width = (x1 - x0) // 3
        col_centers = [x0 + col_width * i + col_width // 2 for i in range(3)]
        labels = ["Prep", "Cook", "Total"]
        values = [prep_text, cook_text, total_text]

        top = y0 + 20
        for idx, (label, value) in enumerate(zip(labels, values)):
            lw, lh = self._get_text_size(draw, label, label_font)
            vw, vh = self._get_text_size(draw, value, value_font)
            cx = col_centers[idx]
            draw.text((cx - lw // 2, top), label, font=label_font, fill=text_fill)
            draw.text((cx - vw // 2, top + lh + 10), value, font=value_font, fill=text_fill)

        draw.line([(x0 + col_width, y0 + 12), (x0 + col_width, y1 - 12)], fill=text_fill, width=1)
        draw.line([(x0 + 2 * col_width, y0 + 12), (x0 + 2 * col_width, y1 - 12)], fill=text_fill, width=1)

    def _draw_banner(self, draw: ImageDraw.Draw, box: Tuple[int, int, int, int], text: str) -> None:
        x0, y0, x1, y1 = self._inset_box(box, 12)
        banner_font = self.fonts.get("default", self.fonts.get("small"))
        bw, bh = self._get_text_size(draw, text, banner_font)
        padding_x = 18
        padding_y = 12
        width_needed = bw + padding_x * 2
        height_needed = bh + padding_y * 2

        cx = (x0 + x1 - width_needed) // 2
        cy = (y0 + y1 - height_needed) // 2
        draw.rounded_rectangle(
            [(cx, cy), (cx + width_needed, cy + height_needed)],
            radius=12,
            outline=0,
            width=2,
        )
        draw.text((cx + padding_x, cy + padding_y), text, font=banner_font, fill=0)

    # ------------------------
    # Main Render
    # ------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs) -> Image.Image:
        layout = self._resolve_layout(kwargs.get("layout"))
        if layout.name == "full":
            return self._render_full(width, height)

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        slots = self._layout_slots(layout, width, height)
        fallback_box = (0, 0, width, height)
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

        meal_text = str(self.meal_details.get("name") or "No dinner planned")
        bottom_of_title = self._draw_title_card(draw, title_box, meal_text)

        if details_box:
            self._draw_time_card(draw, details_box, invert=layout.compact)
        else:
            stacked_box = (title_box[0], bottom_of_title + 10, title_box[2], title_box[3])
            self._draw_time_card(draw, stacked_box)

        start_by = self._compute_start_time(self.meal_details.get("total"))
        target_time = self._parse_target_time()
        target_str = datetime.datetime.combine(datetime.date.today(), target_time)
        target_label = target_str.strftime("%I:%M %p").lstrip("0")

        if start_by:
            banner_text = f"Start by {self._format_clock(start_by)} to eat by {target_label}"
        else:
            banner_text = f"Plan to eat by {target_label}"

        banner_area = footer_box or details_box or title_box
        self._draw_banner(draw, banner_area, banner_text)

        return image
