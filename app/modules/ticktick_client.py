"""Lightweight TickTick API client used by the TickTick module."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

EXPIRED_MESSAGE = (
    "TickTick token expired. Please re-run dumb-smart-display/scripts $ python ticktick_oauth.py  to get a new access_token."
)


@dataclass
class TaskItem:
    """Normalized representation of a TickTick task."""

    title: str
    project_name: str
    date: dt.date
    time: Optional[dt.time]
    is_all_day: bool
    is_completed: bool


class TickTickClient:
    """Thin wrapper around TickTick's REST API."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        tz_name = self.config.get("timezone", "UTC")
        try:
            self.timezone = ZoneInfo(tz_name)
        except Exception:
            log.warning("TickTick timezone '%s' invalid. Falling back to UTC.", tz_name)
            self.timezone = ZoneInfo("UTC")

        # The official TickTick Open API uses the /open/v1 base path for all endpoints.
        # Using the legacy /api/v2 routes will return 404s even with a valid token,
        # which surfaces to the user as "TickTick unavailable".
        self.base_url = self.config.get("base_url", "https://api.ticktick.com/open/v1").rstrip("/")
        self.access_token = self.config.get("access_token", "")
        self.access_token_expires_at = self.config.get("access_token_expires_at")

        self._session = requests.Session()
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[dt.datetime] = None

        self._projects_cache: Dict[str, str] = {}
        self._projects_cache_time: Optional[dt.datetime] = None
        self._projects_ttl = int(self.config.get("projects_cache_seconds", 6 * 3600))

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _parse_datetime(self, value: Any) -> Optional[dt.datetime]:
        if not value:
            return None
        if isinstance(value, dt.datetime):
            parsed = value
        elif isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            try:
                parsed = dt.datetime.fromisoformat(normalized)
            except ValueError:
                log.debug("TickTickClient failed to parse datetime: %s", value)
                return None
        else:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(self.timezone)

    def _ensure_token(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        if self._token_expiry and self._token_expiry <= now:
            raise RuntimeError(EXPIRED_MESSAGE)

        if self._access_token:
            return

        if not self.access_token:
            raise RuntimeError("TickTick access_token is missing")

        self._access_token = self.access_token

        if self.access_token_expires_at:
            expiry = self._parse_datetime(self.access_token_expires_at)
            if expiry:
                self._token_expiry = expiry.astimezone(dt.timezone.utc)
                if self._token_expiry <= now:
                    raise RuntimeError(EXPIRED_MESSAGE)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._ensure_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers.setdefault("Accept", "application/json")

        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.request(method, url, headers=headers, timeout=10, **kwargs)
            resp.raise_for_status()
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else None
            if status == 401:
                raise RuntimeError(EXPIRED_MESSAGE) from err
            raise

        return resp.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_projects_map(self) -> Dict[str, str]:
        now = dt.datetime.now(dt.timezone.utc)
        if (
            self._projects_cache
            and self._projects_cache_time
            and (now - self._projects_cache_time).total_seconds() < self._projects_ttl
        ):
            return self._projects_cache

        payload = self._request("GET", "project")
        mapping = {}
        if isinstance(payload, list):
            for entry in payload:
                pid = entry.get("id") or entry.get("_id")
                if not pid:
                    continue
                mapping[str(pid)] = entry.get("name") or entry.get("title") or "Inbox"

        self._projects_cache = mapping
        self._projects_cache_time = now
        return mapping

    def get_open_tasks_for_range(self, start: dt.date, end: dt.date) -> List[TaskItem]:
        """Return open tasks whose due/start dates fall between start and end (inclusive)."""

        params = {"startDate": start.isoformat(), "endDate": end.isoformat()}
        raw_tasks = self._request("GET", "task", params=params)
        project_lookup = self.get_projects_map()
        normalized: List[TaskItem] = []

        if not isinstance(raw_tasks, list):
            return normalized

        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            item = self._normalize_task(task, project_lookup)
            if item is None:
                continue
            if item.is_completed:
                continue
            if start <= item.date <= end:
                normalized.append(item)

        return normalized

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def _normalize_task(self, task: Dict[str, Any], project_lookup: Dict[str, str]) -> Optional[TaskItem]:
        due_raw = task.get("dueDate") or task.get("due") or task.get("due_date")
        start_raw = task.get("startDate") or task.get("start")

        due_dt = self._parse_datetime(due_raw)
        start_dt = self._parse_datetime(start_raw)
        anchor = due_dt or start_dt

        if anchor is None:
            return None

        is_all_day = bool(task.get("isAllDay")) or (anchor.hour == 0 and anchor.minute == 0 and anchor.second == 0)
        is_completed = bool(task.get("isCompleted")) or task.get("status") in {2, "completed", "done"}
        project_id = str(task.get("projectId") or task.get("project_id") or "")
        project_name = project_lookup.get(project_id, "")

        time_part: Optional[dt.time] = None
        if not is_all_day:
            time_part = anchor.timetz()

        return TaskItem(
            title=str(task.get("title") or task.get("name") or "(Untitled)"),
            project_name=project_name,
            date=anchor.date(),
            time=time_part,
            is_all_day=is_all_day,
            is_completed=is_completed,
        )
