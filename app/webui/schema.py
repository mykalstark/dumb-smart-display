# app/webui/schema.py
"""
Schema definitions for the web configuration UI.

Each entry in MODULE_SCHEMAS maps a config section name to a descriptor dict:
    {
        "label":       Human-readable section title
        "description": One-line summary shown in the Active Modules grid
        "fields":      Ordered list of field descriptors
    }

Field descriptor keys:
    key       Dot-separated path within the section's config dict
              e.g. "api.access_token" → config["api"]["access_token"]
    label     Human-readable label
    type      "text" | "number" | "password" | "select" | "toggle" | "events_list"
    help      Optional helper text shown beneath the field
    required  Bool — rendered with a required indicator (default False)
    options   List of {"value", "label"} dicts — only used for "select" type
    min/max   Optional numeric bounds for "number" type
    placeholder  Optional placeholder text
"""
from __future__ import annotations

from typing import Any, Dict, List

FieldDef = Dict[str, Any]
SectionSchema = Dict[str, Any]

# ---------------------------------------------------------------------------
# Top-level location section
# ---------------------------------------------------------------------------
LOCATION_SCHEMA: SectionSchema = {
    "label": "Location",
    "description": "Shared GPS coordinates used by weather and clock modules.",
    "fields": [
        {
            "key": "latitude",
            "label": "Latitude",
            "type": "number",
            "help": "Decimal degrees, e.g. 40.7128",
            "required": True,
            "placeholder": "40.513217",
        },
        {
            "key": "longitude",
            "label": "Longitude",
            "type": "number",
            "help": "Decimal degrees, e.g. -74.0060",
            "required": True,
            "placeholder": "-112.321445",
        },
        {
            "key": "location_name",
            "label": "Location Name",
            "type": "text",
            "help": "Friendly name shown on the clock screen.",
            "placeholder": "Home",
        },
        {
            "key": "temperature_unit",
            "label": "Temperature Unit",
            "type": "select",
            "options": [
                {"value": "fahrenheit", "label": "Fahrenheit (°F)"},
                {"value": "celsius", "label": "Celsius (°C)"},
            ],
        },
        {
            "key": "time_format",
            "label": "Time Format",
            "type": "select",
            "options": [
                {"value": "12h", "label": "12-hour (2:30 PM)"},
                {"value": "24h", "label": "24-hour (14:30)"},
            ],
            "help": "Applies to all modules that display a time of day.",
        },
    ],
}

# ---------------------------------------------------------------------------
# Hardware / display section
# ---------------------------------------------------------------------------
HARDWARE_SCHEMA: SectionSchema = {
    "label": "Display Settings",
    "description": "Hardware driver and refresh cadence.",
    "fields": [
        {
            "key": "cycle_seconds",
            "label": "Module Cycle Interval (seconds)",
            "type": "number",
            "help": "How long each module is shown before advancing to the next.",
            "min": 5,
            "placeholder": "30",
        },
        {
            "key": "rotation",
            "label": "Screen Rotation",
            "type": "select",
            "options": [
                {"value": "0", "label": "0° (landscape)"},
                {"value": "90", "label": "90° (portrait)"},
                {"value": "180", "label": "180° (landscape, flipped)"},
                {"value": "270", "label": "270° (portrait, flipped)"},
            ],
            "help": "Physical orientation of the panel.",
        },
        {
            "key": "simulate",
            "label": "Simulator Mode",
            "type": "toggle",
            "help": "Show a desktop window instead of driving real hardware. Useful for testing.",
        },
    ],
}

# ---------------------------------------------------------------------------
# Web UI section
# ---------------------------------------------------------------------------
WEBUI_SCHEMA: SectionSchema = {
    "label": "Web UI",
    "description": "Settings for this configuration interface.",
    "fields": [
        {
            "key": "password",
            "label": "Password",
            "type": "password",
            "help": "Protect this page with a password. Leave empty to allow open access on your local network.",
            "placeholder": "Leave empty for no password",
        },
        {
            "key": "port",
            "label": "Port",
            "type": "number",
            "help": "Port the web UI listens on. Requires restart to take effect.",
            "min": 1024,
            "max": 65535,
            "placeholder": "8080",
        },
    ],
}

# ---------------------------------------------------------------------------
# Module schemas
# ---------------------------------------------------------------------------
MODULE_SCHEMAS: Dict[str, SectionSchema] = {
    "clock": {
        "label": "Clock",
        "description": "Time, date, and current weather conditions.",
        "fields": [
            {
                "key": "date_format",
                "label": "Date Format",
                "type": "text",
                "help": "Python strftime format string, e.g. %a %d for 'Fri 26'.",
                "placeholder": "%a %d",
            },
            {
                "key": "time_size",
                "label": "Time Font Size",
                "type": "number",
                "min": 40,
                "max": 200,
                "placeholder": "120",
            },
            {
                "key": "date_size",
                "label": "Date Font Size",
                "type": "number",
                "min": 20,
                "max": 100,
                "placeholder": "50",
            },
            {
                "key": "refresh_seconds",
                "label": "Weather Refresh Interval (seconds)",
                "type": "number",
                "min": 60,
                "placeholder": "1800",
                "help": "How often to fetch current weather from Open-Meteo.",
            },
        ],
    },

    "mealie_today": {
        "label": "Mealie — Tonight's Dinner",
        "description": "Shows tonight's recipe from your self-hosted Mealie instance.",
        "fields": [
            {
                "key": "base_url",
                "label": "Mealie URL",
                "type": "text",
                "required": True,
                "placeholder": "http://192.168.1.100:9000",
                "help": "Base URL of your Mealie server.",
            },
            {
                "key": "api_token",
                "label": "API Token",
                "type": "password",
                "required": True,
                "help": "Generate one in Mealie under your profile → API Tokens.",
            },
            {
                "key": "target_eat_time",
                "label": "Target Dinner Time",
                "type": "time_of_day",
                "help": "When dinner should be ready. Follows the global Time Format setting.",
            },
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 60,
                "placeholder": "3600",
            },
        ],
    },

    "ticktick": {
        "label": "TickTick Tasks",
        "description": "Today's and tomorrow's tasks from TickTick.",
        "fields": [
            {
                "key": "api.access_token",
                "label": "Access Token",
                "type": "password",
                "required": True,
                "help": "OAuth access token from the TickTick Open API developer portal.",
            },
            {
                "key": "api.timezone",
                "label": "Timezone",
                "type": "text",
                "placeholder": "America/Denver",
                "help": "IANA timezone name for due-date comparisons.",
            },
            {
                "key": "max_items_per_day",
                "label": "Max Tasks Per Day",
                "type": "number",
                "min": 1,
                "max": 20,
                "placeholder": "6",
            },
            {
                "key": "max_title_length",
                "label": "Max Title Length (characters)",
                "type": "number",
                "min": 20,
                "max": 200,
                "placeholder": "60",
            },
            {
                "key": "show_project_names",
                "label": "Show Project Names",
                "type": "toggle",
            },
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 60,
                "placeholder": "900",
            },
        ],
    },

    "calendar_ics": {
        "label": "Calendar (iCal/ICS)",
        "description": "Today's and tomorrow's events from any iCal URL (Google, Apple, Outlook…).",
        "fields": [
            {
                "key": "ics_url",
                "label": "iCal URL",
                "type": "text",
                "required": True,
                "placeholder": "https://calendar.google.com/calendar/ical/…/basic.ics",
                "help": (
                    "Your private iCal link. In Google Calendar: Settings → [calendar] → "
                    "'Secret address in iCal format'. Both https:// and webcal:// are accepted."
                ),
            },
            {
                "key": "max_events_per_day",
                "label": "Max Events Per Day",
                "type": "number",
                "min": 1,
                "max": 20,
                "placeholder": "5",
            },
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 60,
                "placeholder": "900",
            },
        ],
    },

    "rss_feed": {
        "label": "RSS Feed",
        "description": "Latest headlines from any RSS or Atom feed.",
        "fields": [
            {
                "key": "feed_url",
                "label": "Feed URL",
                "type": "text",
                "required": True,
                "placeholder": "https://www.goodnewsnetwork.org/feed/",
                "help": "Any RSS 2.0 or Atom feed URL.",
            },
            {
                "key": "max_items",
                "label": "Max Headlines to Load",
                "type": "number",
                "min": 1,
                "max": 50,
                "placeholder": "8",
            },
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 60,
                "placeholder": "1800",
            },
        ],
    },

    "countdown": {
        "label": "Countdown",
        "description": "Days remaining until one or more named events.",
        "fields": [
            {
                "key": "events",
                "label": "Events",
                "type": "events_list",
                "help": "Add one or more events to count down to. Use YYYY-MM-DD date format.",
            },
            {
                "key": "show_past_days",
                "label": "Keep Showing After Event (days)",
                "type": "number",
                "min": 0,
                "placeholder": "7",
                "help": "How many days after the event date to keep showing it. Set to 0 to hide immediately.",
            },
        ],
    },

    "spotify_now_playing": {
        "label": "Spotify Now Playing",
        "description": "Currently playing track, artist, and album from Spotify.",
        "fields": [
            {
                "key": "client_id",
                "label": "Client ID",
                "type": "text",
                "required": True,
                "help": "From your Spotify app at developer.spotify.com/dashboard.",
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "type": "password",
                "required": True,
            },
            {
                "key": "refresh_token",
                "label": "Refresh Token",
                "type": "password",
                "required": True,
                "help": (
                    "One-time setup: see config/config.example.yml for the step-by-step "
                    "curl workflow to get a non-expiring refresh token."
                ),
            },
            {
                "key": "refresh_seconds",
                "label": "Poll Interval (seconds)",
                "type": "number",
                "min": 5,
                "max": 60,
                "placeholder": "10",
                "help": "How often to check what's playing. Spotify allows ~1 request/second.",
            },
        ],
    },

    "system_status": {
        "label": "System Status",
        "description": "Pi health at a glance — CPU temp, RAM, disk, uptime, IP.",
        "fields": [
            {
                "key": "show_ip",
                "label": "Show Local IP Address",
                "type": "toggle",
            },
            {
                "key": "cpu_temp_warn_celsius",
                "label": "CPU Temp Warning Threshold (°C)",
                "type": "number",
                "min": 40,
                "max": 100,
                "placeholder": "70",
                "help": "A warning indicator appears on the temp card when this threshold is exceeded.",
            },
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 10,
                "placeholder": "60",
            },
        ],
    },

    "weather_forecast": {
        "label": "7-Day Weather Forecast",
        "description": "High/low temperatures, weather icons, and precipitation for the next 7 days.",
        "fields": [
            {
                "key": "refresh_seconds",
                "label": "Refresh Interval (seconds)",
                "type": "number",
                "min": 300,
                "placeholder": "3600",
                "help": "Latitude and longitude are inherited from the Location section above.",
            },
        ],
    },
}

# Ordered list of module names — controls display order in the UI
MODULE_ORDER: List[str] = [
    "clock",
    "mealie_today",
    "ticktick",
    "calendar_ics",
    "rss_feed",
    "countdown",
    "spotify_now_playing",
    "system_status",
    "weather_forecast",
]
