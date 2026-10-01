"""iCal calendar module — displays today's and tomorrow's events from any .ics URL."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, LINE_SPACING, draw_card,
    draw_card_header, draw_text_block, draw_message, draw_list, ellipsize,
    fit_font,
)

log = logging.getLogger(__name__)

try:
    import icalendar  # type: ignore
    from dateutil import rrule as dateutil_rrule  # type: ignore
    from dateutil.tz import tzlocal  # type: ignore
    _ICAL_AVAILABLE = True
except ImportError:
    _ICAL_AVAILABLE = False
    log.warning("icalendar or python-dateutil not installed. calendar_ics module disabled.")


# A normalized event suitable for display
class _Event:
    __slots__ = ("title", "event_date", "event_time", "is_all_day")

    def __init__(
        self,
        title: str,
        event_date: date,
        event_time: Optional[time],
        is_all_day: bool,
    ) -> None:
        self.title = title
        self.event_date = event_date
        self.event_time = event_time
        self.is_all_day = is_all_day


def _to_local_date(dt_val: Any) -> Optional[date]:
    """Convert an icalendar DTSTART value to a local date."""
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is not None:
            dt_val = dt_val.astimezone(tzlocal() if _ICAL_AVAILABLE else timezone.utc)
        return dt_val.date()
    if isinstance(dt_val, date):
        return dt_val
    return None


def _to_local_time(dt_val: Any) -> Optional[time]:
    """Extract local time from an icalendar DTSTART value, or None for all-day events."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is not None:
            dt_val = dt_val.astimezone(tzlocal() if _ICAL_AVAILABLE else timezone.utc)
        return dt_val.time().replace(tzinfo=None)
    return None  # date-only → all-day


def _parse_ics(content: bytes, target_dates: Tuple[date, date]) -> List[_Event]:
    """Parse an ICS byte string and return events on any of target_dates."""
    if not _ICAL_AVAILABLE:
        return []

    cal = icalendar.Calendar.from_ical(content)
    events: List[_Event] = []
    start_target, end_target = target_dates

    # Build a window: midnight of start_target → end of end_target (local tz)
    local_tz = tzlocal()
    window_start = datetime.combine(start_target, time.min).replace(tzinfo=local_tz)
    window_end = datetime.combine(end_target, time.max).replace(tzinfo=local_tz)

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart_prop = component.get("DTSTART")
        if dtstart_prop is None:
            continue
        dtstart = dtstart_prop.dt

        title_prop = component.get("SUMMARY")
        title = str(title_prop) if title_prop else "(No title)"

        rrule_prop = component.get("RRULE")

        if rrule_prop:
            # Recurring event — expand within the window
            try:
                rrule_str = rrule_prop.to_ical().decode()
                if isinstance(dtstart, datetime):
                    dtstart_aware = dtstart if dtstart.tzinfo else dtstart.replace(tzinfo=local_tz)
                else:
                    # date-only start — treat as midnight local
                    dtstart_aware = datetime.combine(dtstart, time.min).replace(tzinfo=local_tz)

                rule = dateutil_rrule.rrulestr(
                    rrule_str, dtstart=dtstart_aware, ignoretz=False
                )
                occurrences = rule.between(window_start, window_end, inc=True)
                for occ in occurrences:
                    ev_date = occ.astimezone(local_tz).date()
                    ev_time = occ.astimezone(local_tz).time().replace(tzinfo=None)
                    is_all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
                    if is_all_day:
                        ev_time = None
                    events.append(_Event(title, ev_date, ev_time, is_all_day))
            except Exception as exc:
                log.debug("Failed to expand RRULE for '%s': %s", title, exc)
        else:
            # Non-recurring event
            ev_date = _to_local_date(dtstart)
            if ev_date is None:
                continue
            if ev_date < start_target or ev_date > end_target:
                continue
            is_all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
            ev_time = None if is_all_day else _to_local_time(dtstart)
            events.append(_Event(title, ev_date, ev_time, is_all_day))

    return events


class Module(BaseDisplayModule):
    name = "calendar_ics"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        raw_url: str = self.config.get("ics_url", "")
        # webcal:// is identical to https:// for fetching purposes
        self.ics_url: str = raw_url.replace("webcal://", "https://", 1)
        self.time_format: str = self.config.get("time_format", "%I:%M %p")
        self.max_events_per_day: int = int(self.config.get("max_events_per_day", 5))
        self.refresh_seconds: int = int(self.config.get("refresh_seconds", 900))

        self._today_events: List[_Event] = []
        self._tomorrow_events: List[_Event] = []
        self._last_fetch: Optional[datetime] = None
        self._last_updated: Optional[datetime] = None
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def tick(self) -> None:
        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch).total_seconds() < self.refresh_seconds:
            return
        self._fetch()

    def handle_button(self, event: str) -> None:
        if event == "refresh":
            self._fetch()

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    def _fetch(self) -> None:
        self._last_fetch = datetime.now()

        if not _ICAL_AVAILABLE:
            self._error = "icalendar not installed"
            return
        if not self.ics_url:
            self._error = "No ics_url configured"
            return

        try:
            resp = requests.get(self.ics_url, timeout=10)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("calendar_ics: fetch failed: %s", exc)
            self._error = "Calendar unavailable"
            return

        today = date.today()
        tomorrow = today + timedelta(days=1)

        try:
            all_events = _parse_ics(resp.content, (today, tomorrow))
        except Exception as exc:
            log.warning("calendar_ics: parse failed: %s", exc)
            self._error = "Could not parse calendar"
            return

        def _sort_key(ev: _Event) -> Tuple:
            return (0 if ev.event_time else 1, ev.event_time or time.min)

        today_evs = sorted(
            [e for e in all_events if e.event_date == today], key=_sort_key
        )
        tomorrow_evs = sorted(
            [e for e in all_events if e.event_date == tomorrow], key=_sort_key
        )

        self._today_events = today_evs[: self.max_events_per_day]
        self._tomorrow_events = tomorrow_evs[: self.max_events_per_day]
        self._error = None
        self._last_updated = datetime.now()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _draw_centered(self, draw, width, height, text):
        draw_message(draw, width, height, text, self.fonts.get("default"))

    def _format_event_line(self, ev, max_width, draw, font):
        if ev.is_all_day or ev.event_time is None:
            prefix = "• "
        else:
            prefix = ev.event_time.strftime(self.time_format).lstrip("0") + " "
        return ellipsize(draw, prefix + ev.title, font, max_width)

    def _draw_column(self, draw, box, heading, events):
        x0, y0, x1, y1 = box
        draw_card(draw, *box)
        header_font = self.fonts.get("large", self.fonts.get("default"))
        body_font = self.fonts.get("default")
        small_font = self.fonts.get("small", body_font)
        content_top = draw_card_header(draw, x0, y0, x1, heading, header_font)
        content_w = x1 - x0 - 2 * INNER_PAD
        body_font = fit_font(draw, "10:00 AM Event", body_font, content_w, 32)
        draw_list(draw, (x0 + INNER_PAD, content_top + INNER_PAD, x1 - INNER_PAD, y1 - INNER_PAD),
                  [self._format_event_line(ev, content_w, draw, body_font) for ev in events],
                  body_font, small_font, empty="No events", max_lines=1)

    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self.tick()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        if self._error:
            self._draw_centered(draw, width, height, self._error)
            return image

        padding = OUTER_PAD
        gap = COL_GAP
        usable_w = width - padding * 2
        col_w = (usable_w - gap) // 2

        today = date.today()
        tomorrow = today + timedelta(days=1)

        # %-d (no zero-padding) is POSIX-only; build the heading manually for
        # cross-platform compatibility (Linux Pi + Windows dev environment).
        today_heading = today.strftime("%A") + " " + str(today.day)
        tomorrow_heading = tomorrow.strftime("%A") + " " + str(tomorrow.day)

        small_font = self.fonts.get("small", self.fonts.get("default"))
        footer_h = 28 + LINE_SPACING if self._last_updated else 0
        card_bottom = height - padding - footer_h
        today_box = (padding, padding, padding + col_w, card_bottom)
        tomorrow_box = (padding + col_w + gap, padding, width - padding, card_bottom)

        self._draw_column(draw, today_box, today_heading, self._today_events)
        self._draw_column(draw, tomorrow_box, tomorrow_heading, self._tomorrow_events)

        if self._last_updated:
            draw_text_block(draw, (padding, card_bottom + LINE_SPACING, width - padding, height - padding),
                            f"Updated {self._last_updated.strftime(self.time_format)}", small_font)
        return image
