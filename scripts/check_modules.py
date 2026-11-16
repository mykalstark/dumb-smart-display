"""Check configured modules without printing URLs, credentials, or personal data.

Run from the project root: .venv/bin/python scripts/check_modules.py --all
This reads services using the existing configuration and never saves settings.
"""
from __future__ import annotations

import argparse
import copy
import io
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import build_module_manager, load_config, load_fonts
from app.webui.schema import MODULE_ORDER


def configuration_problem(module):
    if module.name in {"clock", "weather_forecast"}:
        if module.latitude is None or module.longitude is None:
            return "Weather coordinates are unset; select a location in Settings."
    if module.name == "calendar_ics":
        from app.modules.calendar_ics import _ICAL_AVAILABLE
        if not _ICAL_AVAILABLE:
            return "Calendar dependencies are missing; install requirements in this Python environment."
        if not module.ics_url or module.ics_url == "CHANGE_ME":
            return "Calendar URL is not configured."
    if module.name == "spotify_now_playing" and not module._credentials_configured():
        return "Spotify credentials are not configured."
    if module.name == "ticktick":
        token = module.config.get("api", {}).get("access_token")
        if not token or token == "CHANGE_ME":
            return "TickTick access token is not configured."
    if module.name == "mealie_today":
        if (not module.base_url or not module.api_token or "192.168.xx.yy" in module.base_url
                or module.api_token == "CHANGE_ME"):
            return "Mealie URL/token is not configured."
    return None


def inspect_module(module, http):
    failures = [status for status in http if not isinstance(status, int) or status >= 400]
    if failures:
        # Status codes and exception classes are safe; exception messages and
        # response bodies can contain private calendar URLs or access tokens.
        detail = ", ".join(f"HTTP {value}" if isinstance(value, int) else value for value in failures)
        return "ERROR", f"Service request failed: {detail}."
    if getattr(module, "_error", None) or getattr(module, "error_message", None):
        return "ERROR", "The module reported a data/dependency error."
    if module.name == "clock" and all(value is None for value in module.weather.values()):
        return "EMPTY", "No weather measurements returned."
    if module.name == "weather_forecast" and not module._days:
        return "EMPTY", "No forecast days returned."
    if module.name == "system_status" and not module._stats:
        return "ERROR", "No system measurements collected."
    empty = getattr(module, "is_empty", None)
    if callable(empty) and empty():
        return "EMPTY", "No content for the current date/playback window; rendering passed."
    return "OK", "Data loaded and rendering passed."


def check_module(config, name, fonts):
    http = []
    original_request = requests.sessions.Session.request

    def observed_request(session, *args, **kwargs):
        try:
            response = original_request(session, *args, **kwargs)
        except requests.RequestException as exc:
            http.append(type(exc).__name__)
            raise
        http.append(response.status_code)
        return response

    settings = copy.deepcopy(config)
    settings.setdefault("modules", {})["enabled"] = [name]
    suppressed = io.StringIO()
    previous_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(suppressed), redirect_stderr(suppressed), \
             patch.object(requests.sessions.Session, "request", observed_request):
            manager = build_module_manager(settings, fonts)
            if not manager.modules:
                return "ERROR", "Module import failed."
            module = manager.modules[0]
            problem = configuration_problem(module)
            if problem:
                return "SETUP", problem
            # Use the real data parser and render path, without driving hardware.
            module.tick()
            frame = module.render(800, 480)
            if frame.size != (800, 480):
                return "ERROR", "Module returned an unexpected image size."
            return inspect_module(module, http)
    except Exception as exc:
        return "ERROR", f"Module initialization, fetch, or render failed ({type(exc).__name__})."
    finally:
        logging.disable(previous_level)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/config.yml"))
    parser.add_argument("--all", action="store_true", help="Also check disabled built-in modules.")
    args = parser.parse_args()
    print("Device time:", datetime.now().astimezone().isoformat(timespec="seconds"))
    for package in ("requests", "icalendar", "recurring-ical-events", "python-dateutil", "feedparser", "psutil"):
        try:
            installed = version(package)
        except PackageNotFoundError:
            installed = "MISSING"
        print(f"Dependency {package}: {installed}")
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"ERROR: Could not read configuration ({type(exc).__name__}).")
        return 1
    enabled = config.get("modules", {}).get("enabled") or []
    names = list(dict.fromkeys([*enabled, *(MODULE_ORDER if args.all else [])]))
    fonts = load_fonts()
    failed = False
    for name in names:
        state, detail = check_module(config, name, fonts)
        enabled_label = "enabled" if name in enabled else "disabled"
        print(f"{name} ({enabled_label}): {state} — {detail}", flush=True)
        failed |= state in {"ERROR", "SETUP"} and name in enabled
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
