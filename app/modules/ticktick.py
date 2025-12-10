"""TickTick task viewer module."""
from __future__ import annotations

import datetime as dt
import logging
import textwrap
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.modules.ticktick_client import TaskItem, TickTickClient

log = logging.getLogger(__name__)


class Module(BaseDisplayModule):
    name = "ticktick"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]):
        self.config = config or {}
        self.fonts = fonts

        self.client = TickTickClient(self.config.get("api", {}))

        self.refresh_seconds = int(self.config.get("refresh_seconds", 900))
        self.max_items_per_day = int(self.config.get("max_items_per_day", 6))
        self.show_project_names = bool(self.config.get("show_project_names", True))
        self.title_max_length = int(self.config.get("max_title_length", 60))
        self.time_format = self.config.get("time_format", "%H:%M")

        self.timezone = self.client.timezone

        self.today_tasks: List[TaskItem] = []
        self.tomorrow_tasks: List[TaskItem] = []
        self.today_overflow: int = 0
        self.tomorrow_overflow: int = 0
        self.last_fetch: Optional[dt.datetime] = None
        self.error_message: Optional[str] = None

        self._default_layout = DEFAULT_LAYOUTS[0]
        self._layout_lookup = {layout.name: layout for layout in DEFAULT_LAYOUTS}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def tick(self) -> None:
        now = dt.datetime.now(self.client.timezone)
        if self.last_fetch and (now - self.last_fetch).total_seconds() < self.refresh_seconds:
            return

        try:
            today = now.date()
            tomorrow = today + dt.timedelta(days=1)
            tasks = self.client.get_open_tasks_for_range(today, tomorrow)
            grouped_today = [t for t in tasks if t.date == today]
            grouped_tomorrow = [t for t in tasks if t.date == tomorrow]

            self.today_tasks = self._sorted_limited(grouped_today)
            self.tomorrow_tasks = self._sorted_limited(grouped_tomorrow)
            self.today_overflow = max(0, len(grouped_today) - len(self.today_tasks))
            self.tomorrow_overflow = max(0, len(grouped_tomorrow) - len(self.tomorrow_tasks))
            self.error_message = None
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("TickTick update failed: %s", exc)
            if isinstance(exc, RuntimeError):
                self.error_message = "TickTick auth error"
            else:
                self.error_message = "TickTick unavailable"
            self.today_tasks = []
            self.tomorrow_tasks = []
            self.today_overflow = 0
            self.tomorrow_overflow = 0

        self.last_fetch = now

    def handle_button(self, event: str) -> None:
        # No interactive actions yet.
        return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _sorted_limited(self, tasks: List[TaskItem]) -> List[TaskItem]:
        sorted_tasks = sorted(tasks, key=self._task_sort_key)
        if self.max_items_per_day:
            return sorted_tasks[: self.max_items_per_day]
        return sorted_tasks

    def _task_sort_key(self, task: TaskItem) -> Tuple[int, dt.time]:
        time_val = (task.time.replace(tzinfo=None) if task.time else dt.time(23, 59, 59))
        return (0 if task.time else 1, time_val)

    def _truncate_title(self, title: str) -> str:
        if len(title) <= self.title_max_length:
            return title
        return title[: max(self.title_max_length - 1, 1)] + "…"

    def _format_task_line(self, task: TaskItem) -> str:
        if task.is_all_day or task.time is None:
            prefix = "[•]"
        else:
            prefix = f"[{task.time.strftime(self.time_format)}]"

        title = self._truncate_title(task.title)
        if self.show_project_names and task.project_name:
            title = f"{title} ({task.project_name})"
        return f"{prefix} {title}"

    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        except AttributeError:  # pragma: no cover - fallback
            return draw.textsize(text, font=font)

    def _wrap_text(self, draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> List[str]:
        width_per_char = max(self._get_text_size(draw, "M", font)[0], 1)
        approx_chars = max_width // width_per_char
        wrapper = textwrap.TextWrapper(width=max(approx_chars, 1))
        return wrapper.wrap(text)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (self._layout_lookup.get("full", self._default_layout),)

    def render(self, width: int, height: int, **kwargs: Any) -> Image.Image:
        if self.last_fetch is None:
            self.tick()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        if self.error_message:
            self._draw_centered(draw, width, height, self.error_message)
            return image

        padding = 24
        column_gap = 12
        usable_width = width - (padding * 2) - column_gap
        column_width = usable_width // 2
        header_font = self.fonts.get("large", self.fonts.get("default"))
        body_font = self.fonts.get("default")
        small_font = self.fonts.get("small", body_font)

        today_box = (padding, padding, padding + column_width, height - padding)
        tomorrow_box = (
            padding + column_width + column_gap,
            padding,
            width - padding,
            height - padding,
        )

        self._draw_section(draw, today_box, "Today", self.today_tasks, self.today_overflow, header_font, body_font, small_font)
        self._draw_section(
            draw,
            tomorrow_box,
            "Tomorrow",
            self.tomorrow_tasks,
            self.tomorrow_overflow,
            header_font,
            body_font,
            small_font,
        )

        return image

    def _draw_centered(self, draw: ImageDraw.ImageDraw, width: int, height: int, text: str) -> None:
        font = self.fonts.get("default")
        tw, th = self._get_text_size(draw, text, font)
        draw.text(((width - tw) // 2, (height - th) // 2), text, font=font, fill=0)

    def _draw_section(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        title: str,
        tasks: List[TaskItem],
        overflow: int,
        header_font: Any,
        body_font: Any,
        small_font: Any,
    ) -> None:
        x0, y0, x1, y1 = box
        draw.rectangle(box, outline=0, width=2)
        title_w, title_h = self._get_text_size(draw, title, header_font)
        draw.text((x0 + 12, y0 + 8), title, font=header_font, fill=0)

        line_y = y0 + title_h + 20
        max_width = (x1 - x0) - 24

        if not tasks:
            placeholder = "No tasks" if overflow == 0 else "Tasks hidden"
            draw.text((x0 + 12, line_y), placeholder, font=body_font, fill=0)
            return

        for task in tasks:
            line = self._format_task_line(task)
            wrapped = self._wrap_text(draw, line, body_font, max_width)
            for segment in wrapped:
                draw.text((x0 + 12, line_y), segment, font=body_font, fill=0)
                _, lh = self._get_text_size(draw, segment, body_font)
                line_y += lh + 6
                if line_y >= y1 - 40:
                    break
            if line_y >= y1 - 40:
                break

        if overflow > 0 and line_y < y1 - 20:
            overflow_text = f"+{overflow} more…"
            draw.text((x0 + 12, y1 - 28), overflow_text, font=small_font, fill=0)
