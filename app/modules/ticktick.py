"""TickTick task viewer module."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, draw_card, draw_card_header,
    draw_message, draw_list, fit_font,
)
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

    def is_empty(self) -> bool:
        return (
            self.last_fetch is not None
            and not self.error_message
            and not (self.today_tasks or self.tomorrow_tasks or self.today_overflow or self.tomorrow_overflow)
        )

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
                self.error_message = str(exc) or "TickTick auth error"
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

        padding = OUTER_PAD
        column_gap = COL_GAP
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

    def _draw_centered(self, draw, width, height, text):
        draw_message(draw, width, height, text, self.fonts.get("default"))

    def _draw_section(self, draw, box, title, tasks, overflow, header_font, body_font, small_font):
        x0, y0, x1, y1 = box
        draw_card(draw, *box)
        content_top = draw_card_header(draw, x0, y0, x1, title, header_font)
        body_font = fit_font(draw, "[09:30] Task", body_font, x1 - x0 - 2 * INNER_PAD, 32)
        draw_list(draw, (x0 + INNER_PAD, content_top + INNER_PAD, x1 - INNER_PAD, y1 - INNER_PAD),
                  [self._format_task_line(task) for task in tasks], body_font, small_font,
                  overflow=overflow, empty="No tasks" if not overflow else f"+{overflow} more…")
