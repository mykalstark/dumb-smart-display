# Display module API

This document defines the shared contract for modules loaded by the Dumb Smart Display. It is intended to be a concise reference when creating or updating modules.

## Module shape

Each module should expose a `Module` class that follows the [`DisplayModule` protocol](../app/core/module_interface.py):

- **name**: Human-readable identifier used for navigation and logs.
- **`__init__(config, fonts)`**: Constructor receives a module-specific `config` mapping and a shared `fonts` dictionary.
- **`render(width, height, **kwargs) -> PIL.Image.Image`**: Produce the frame for the current cycle. The display driver supplies the `width` and `height`.
- **`tick() -> None`**: Perform background or periodic work (e.g., refreshing cached data). This is called for all modules, not just the active one.
- **`handle_button(event: str) -> None`**: React to logical button events (`"prev"`, `"next"`, or `"action"`).

### Optional hooks

- **`refresh_interval() -> Optional[int]`**: Hint (in seconds) for how often the module would like to refresh. Return `None` to defer to the default cadence.
- **`supported_layouts() -> Sequence[LayoutPreset]`**: Advertise the layout variants that the module knows how to render. If not implemented, consumers should assume only the `"full"` preset is available.

If you prefer not to reimplement optional hooks, inherit from `BaseDisplayModule` to get default implementations for `refresh_interval` and `supported_layouts`.

## Layout presets

Layout presets live alongside the protocol in [`app/core/module_interface.py`](../app/core/module_interface.py) and capture the shapes shown in the planning reference image. Presets are expressed as `LayoutPreset` dataclasses built from a simple grid definition:

```python
LayoutPreset(
    name="full",
    columns=4,
    rows=2,
    slots=(LayoutSlot("main", colspan=4, rowspan=2),),
    description="Single canvas taking the full display area.",
)
```

A preset describes:

- **name**: A stable identifier.
- **columns / rows**: Grid dimensions the slots map to.
- **slots**: Ordered `LayoutSlot` entries with a `key`, `colspan`, and `rowspan`. The order lets consumers assign content deterministically.
- **description**: Human-readable summary for documentation or UI hints.
- **compact**: Boolean flag to indicate denser layouts suitable for smaller displays.

### Available presets

`DEFAULT_LAYOUTS` currently includes the following options:

| Name | Description | Columns x Rows | Slots | Compact |
| --- | --- | --- | --- | --- |
| `full` | Single canvas taking the full display area. | 4 x 2 | 1 | No |
| `wide_left` | Large area on the left with a tall sidebar on the right. | 4 x 2 | 2 | No |
| `wide_right` | Large area on the right with two stacked panels on the left. | 4 x 2 | 3 | No |
| `three_column` | Three columns with mixed tall and short cards. | 3 x 2 | 5 | No |
| `quads` | Four even quadrants for equally weighted content. | 2 x 2 | 4 | No |
| `compact_quads` | Narrow header with stacked compact cards beneath. | 2 x 3 | 5 | Yes |
| `striped_rows` | Mixed stripes with a wide header row and smaller tiles below. | 3 x 2 | 5 | Yes |

Modules that support multiple layouts should order them by preference in `supported_layouts`, with the most preferred first. Consumers can use the `compact` flag to pick denser options when screen real estate is limited.

---

## Built-in modules

All modules live in `app/modules/`. Enable them by adding their name to `modules.enabled` in `config/config.yml`.

### `clock`
**File:** `app/modules/clock.py`
**Purpose:** Time, date, and current weather.
**Dependencies:** none (uses Open-Meteo, no API key)
**Required config:** `latitude`, `longitude` (for weather; module works without them, just no weather)
**Button behaviour:** None — navigates between modules.

---

### `mealie_today`
**File:** `app/modules/mealie_today.py`
**Purpose:** Tonight's dinner from a self-hosted [Mealie](https://mealie.io) instance, with a recommended kitchen start time.
**Dependencies:** none extra
**Required config:** `base_url`, `api_token`

---

### `ticktick`
**File:** `app/modules/ticktick.py`
**Purpose:** Today's and tomorrow's tasks from [TickTick](https://ticktick.com) (Open API).
**Dependencies:** none extra
**Required config:** `api.access_token` (see config example for token setup notes)

---

### `calendar_ics`
**File:** `app/modules/calendar_ics.py`
**Purpose:** Today's and tomorrow's events from any iCal/ICS URL (Google Calendar, Apple Calendar, Outlook, Nextcloud, etc.).
**Dependencies:** `icalendar>=5.0`, `python-dateutil>=2.8`
**Required config:** `ics_url` — your private iCal link (see config example for where to find it in each app)
**Notes:**
- `webcal://` URLs are automatically rewritten to `https://`
- Recurring events (RRULE) are expanded correctly
- All-day events show with a bullet; timed events show their start time

---

### `rss_feed`
**File:** `app/modules/rss_feed.py`
**Purpose:** Latest headlines from any RSS or Atom feed. Defaults to Good News Network.
**Dependencies:** `feedparser>=6.0`
**Required config:** `feed_url`
**Button behaviour:** `next` / `back` pages through headlines; `refresh` forces a re-fetch.

---

### `countdown`
**File:** `app/modules/countdown.py`
**Purpose:** Days remaining until one or more named events. No network required — pure date math.
**Dependencies:** none extra
**Required config:** At least one entry under `events` with `name` and `date` (YYYY-MM-DD).
**Button behaviour:** `next` / `back` cycles between multiple events.

---

### `spotify_now_playing`
**File:** `app/modules/spotify_now_playing.py`
**Purpose:** Shows the currently playing Spotify track, artist, and album. Works with a free Spotify account.
**Dependencies:** none extra (`requests` already required)
**Required config:** `client_id`, `client_secret`, `refresh_token`
**Setup:** See the detailed instructions in `config/config.example.yml` — it's a one-time curl workflow to get a `refresh_token` that does not expire.
**Button behaviour:** Display only; buttons navigate between modules as usual.

---

### `system_status`
**File:** `app/modules/system_status.py`
**Purpose:** Pi health at a glance — CPU temperature, CPU usage, RAM, disk, uptime, and local IP. No internet required.
**Dependencies:** `psutil>=5.9`
**Required config:** none (all optional)
**Notes:**
- CPU temperature is read from `psutil.sensors_temperatures()` on Linux; falls back to `/sys/class/thermal/thermal_zone0/temp` on Pi.
- Works cross-platform (Windows/Mac) for simulator development — temperature shows "N/A" on non-Linux hosts.
- A small warning indicator appears on the CPU temp card when temperature exceeds `cpu_temp_warn_celsius`.

---

### `weather_forecast`
**File:** `app/modules/weather_forecast.py`
**Purpose:** 7-day weather forecast — high/low temps, a geometric weather icon, and precipitation amount per day. Uses Open-Meteo (free, no API key).
**Dependencies:** none extra (`requests` already required)
**Required config:** `latitude` and `longitude` — automatically inherited from the top-level `location:` block if set there.

**Shared location config:** Rather than setting coordinates in each module, add a `location:` section at the top of `config.yml`. Both `clock` and `weather_forecast` will inherit these values automatically. Module-specific overrides still work.

```yaml
location:
  latitude: 40.513217
  longitude: -112.321445
  temperature_unit: "fahrenheit"
  location_name: "Home"
```

**Icon types drawn with Pillow (1-bit, no images required):**

| WMO codes | Icon |
|-----------|------|
| 0–1 (clear) | Sun — circle + 8 rays |
| 2 (partly cloudy) | Sun + cloud overlap |
| 3 (overcast) | Cloud blob |
| 45, 48 (fog) | Three horizontal rounded bars |
| 51–57 (drizzle) | Cloud + small dots |
| 61–67, 80–82 (rain) | Cloud + diagonal rain lines |
| 71–77, 85–86 (snow) | Cloud + six-pointed snowflake symbols |
| 95–99 (thunderstorm) | Filled cloud + lightning bolt |

**Precipitation** is shown below the low temp only on days where Open-Meteo reports `precipitation_sum > 0`. Displayed in inches (fahrenheit mode) or mm (celsius mode).
