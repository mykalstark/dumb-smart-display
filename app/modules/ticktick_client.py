"""Lightweight TickTick API client used by the TickTick module."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)


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

        self.base_url = self.config.get("base_url", "https://api.ticktick.com/api/v2").rstrip("/")
        self.token_url = self.config.get("token_url", "https://ticktick.com/oauth/token")
        self.client_id = self.config.get("client_id", "")
        self.client_secret = self.config.get("client_secret", "")
        self.refresh_token = self.config.get("refresh_token", "")

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
        if self._access_token and self._token_expiry and self._token_expiry > now + dt.timedelta(seconds=30):
            return

        if not self.refresh_token or not self.client_id or not self.client_secret:
            raise RuntimeError("TickTick credentials are missing")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        resp = self._session.post(self.token_url, data=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        self._token_expiry = now + dt.timedelta(seconds=max(expires_in - 60, 60))

        if not self._access_token:
            raise RuntimeError("TickTick did not return an access token")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._ensure_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers.setdefault("Accept", "application/json")

        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = self._session.request(method, url, headers=headers, timeout=10, **kwargs)
        resp.raise_for_status()
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

        payload = self._request("GET", "projects")
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

        raw_tasks = self._request("GET", "tasks")
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
