"""Helper script to verify TickTick API connectivity using the configured access token.

Run this script from the project root. It loads the TickTick API configuration from
``config/config.yml`` (or the example config as a fallback), performs a couple of API
calls, and logs results to stdout. This helps troubleshoot "ticktick unavailable" issues
by validating the access token and the expected endpoints.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure the repository root is on sys.path so we can import app modules when the script is
# executed directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import DEFAULT_CONFIG_FALLBACK, DEFAULT_CONFIG_PATH, load_config
from app.modules.ticktick_client import TickTickClient


def _masked_token(token: str, visible: int = 4) -> str:
    if not token:
        return "(missing)"
    if len(token) <= visible:
        return token
    return f"{'*' * (len(token) - visible)}{token[-visible:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test TickTick API connectivity.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to YAML configuration file (default: config/config.yml)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Override the access token from config (useful for quick tests)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="How many days ahead to fetch tasks for (default: 3)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser.parse_args()


def load_ticktick_config(path: Path, override_token: Optional[str]) -> Dict[str, Any]:
    config = load_config(path)
    ticktick_cfg = (
        config.get("modules", {})
        .get("settings", {})
        .get("ticktick", {})
        .get("api", {})
    )
    if override_token:
        ticktick_cfg = {**ticktick_cfg, "access_token": override_token}
    return ticktick_cfg


def log_header(client_cfg: Dict[str, Any]) -> None:
    base_url = client_cfg.get("base_url", "(unset)")
    token = client_cfg.get("access_token", "")
    expires = client_cfg.get("access_token_expires_at") or "(unset)"
    tz = client_cfg.get("timezone", "UTC")

    logging.info("Base URL: %s", base_url)
    logging.info("Access token: %s", _masked_token(token))
    logging.info("Token expiry: %s", expires)
    logging.info("Timezone: %s", tz)


def run_checks(client_cfg: Dict[str, Any], days: int) -> None:
    if not client_cfg.get("access_token"):
        raise RuntimeError("TickTick access token is missing from configuration")

    client = TickTickClient(client_cfg)
    log_header(client_cfg)

    logging.info("Testing project listing…")
    projects = client.get_projects_map()
    logging.info("Retrieved %d projects", len(projects))
    for pid, name in projects.items():
        logging.debug("Project %s -> %s", pid, name)

    today = dt.date.today()
    end = today + dt.timedelta(days=max(days - 1, 0))
    logging.info("Testing task retrieval for %s to %s", today.isoformat(), end.isoformat())
    tasks = client.get_open_tasks_for_range(today, end)
    logging.info("Retrieved %d open tasks", len(tasks))
    for task in tasks:
        when = "all-day" if task.is_all_day else task.time.strftime("%H:%M") if task.time else "--:--"
        logging.debug("[%s] %s (%s) - %s", task.date.isoformat(), task.title, when, task.project_name)


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        logging.warning("Config file %s not found. Falling back to %s.", config_path, DEFAULT_CONFIG_FALLBACK)
        config_path = DEFAULT_CONFIG_FALLBACK

    try:
        client_config = load_ticktick_config(config_path, args.token)
        run_checks(client_config, args.days)
    except Exception:  # noqa: BLE001
        logging.exception("TickTick connectivity test failed")
        sys.exit(1)

    logging.info("TickTick connectivity test completed successfully")
