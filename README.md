# Dumb Smart Display

**Dumb Smart Display** is a modular, Raspberry Pi-powered information dashboard designed to look great on E-Ink or LCD screens. It focuses on local control, simple Python modules, and zero-maintenance operation.

- **Hardware**: Raspberry Pi Zero 2 W + Waveshare E-Ink Display + Physical Buttons
- **Software**: A Python rendering engine + a browser-based configuration UI
- **Philosophy**: Your data, your screen, no mandatory cloud ecosystem

---

## Features

- **Modular Design** — Enable/disable modules from a browser UI or a single YAML file
- **Web Configuration UI** — Full settings editor, live update checker, and one-click update & restart at any IP on your network
- **Plug-and-Play Installation** — One script sets up everything on Raspberry Pi OS
- **Hardware Agnostic** — Supports Waveshare E-Ink displays (SPI) and a built-in simulator for PC development
- **Extensible** — Write your own modules in Python using the standard Pillow (PIL) library

---

## Included Modules

### Clock (`clock`)
The default home screen. Shows the current time in large text alongside today's date and live weather pulled from Open-Meteo (no API key required).

| Config key | Type | Default | Description |
|---|---|---|---|
| `time_format` | string | `%H:%M` | strftime format for the time |
| `date_format` | string | `%a, %b %d` | strftime format for the date |
| `time_size` | number | `100` | Font size for the time |
| `date_size` | number | `40` | Font size for the date |
| `refresh_seconds` | number | `1800` | Weather data refresh cadence |
| `latitude` | number | *(from Location)* | Override global latitude |
| `longitude` | number | *(from Location)* | Override global longitude |

**Layouts:** full, wide_left, quads, compact_quads

---

### 7-Day Weather Forecast (`weather_forecast`)
A full-screen 7-column forecast grid. Each column shows the day name, date, a geometric weather icon, high/low temperatures, and precipitation. Today's column is inverted (white on black) for at-a-glance emphasis. No API key required.

| Config key | Type | Default | Description |
|---|---|---|---|
| `refresh_seconds` | number | `3600` | Forecast refresh cadence |
| `latitude` | number | *(from Location)* | Override global latitude |
| `longitude` | number | *(from Location)* | Override global longitude |

**Layouts:** full

---

### Mealie — Tonight's Dinner (`mealie_today`)
Integrates with your self-hosted [Mealie](https://nightly.mealie.io/) meal-planning instance. Shows tonight's dinner recipe, prep/cook/total times, and a calculated "start by" time to ensure dinner is ready when you want it.

| Config key | Type | Default | Description |
|---|---|---|---|
| `base_url` | string | *(required)* | Mealie server URL, e.g. `http://192.168.1.10:9000` |
| `api_token` | string | *(required)* | API bearer token from your Mealie profile |
| `target_eat_time` | string | `18:30` | When dinner should be ready (`HH:MM`) |
| `refresh_seconds` | number | `3600` | Meal plan refresh cadence |

**Layouts:** full, wide_right, striped_rows, compact_quads

---

### TickTick Tasks (`ticktick`)
Displays your TickTick tasks for Today and Tomorrow in a two-column layout. Uses the TickTick Open API v1.

| Config key | Type | Default | Description |
|---|---|---|---|
| `api.access_token` | string | *(required)* | OAuth access token from the TickTick developer portal |
| `api.timezone` | string | `America/Denver` | IANA timezone for due-date calculations |
| `max_items_per_day` | number | `6` | Max tasks shown per day column |
| `max_title_length` | number | `60` | Truncate long task titles to this length |
| `time_format` | string | `%H:%M` | Display format for task times |
| `show_project_names` | toggle | `true` | Show `(ProjectName)` after each task |
| `refresh_seconds` | number | `900` | Task list refresh cadence |

**Layouts:** full

---

### Calendar (`calendar_ics`)
Shows today's and tomorrow's events from any standard iCal URL — Google Calendar, Apple Calendar, Outlook, and more. Handles recurring events via RRULE expansion.

| Config key | Type | Default | Description |
|---|---|---|---|
| `ics_url` | string | *(required)* | Private iCal/webcal URL |
| `time_format` | string | `%I:%M %p` | Display format for event times |
| `max_events_per_day` | number | `5` | Max events shown per day column |
| `refresh_seconds` | number | `900` | Calendar refresh cadence |

**Layouts:** full

---

### RSS Feed (`rss_feed`)
Displays headlines from any RSS 2.0 or Atom feed. Physical buttons page through headlines; the refresh button re-fetches the feed immediately.

| Config key | Type | Default | Description |
|---|---|---|---|
| `feed_url` | string | *(required)* | RSS or Atom feed URL |
| `max_items` | number | `8` | Max headlines to load from the feed |
| `refresh_seconds` | number | `1800` | Feed refresh cadence |

**Layouts:** full

---

### Countdown (`countdown`)
Counts down to one or more upcoming events. Shows a large day count, "TODAY" when the date arrives, and how many days ago past events were. Physical buttons cycle between events.

| Config key | Type | Description |
|---|---|---|
| `events` | list | Each entry: `{ name: "Event Name", date: "YYYY-MM-DD" }` |
| `show_past_days` | number | Keep showing an event for this many days after it passes (default: `7`) |

**Layouts:** full

---

### Spotify Now Playing (`spotify_now_playing`)
Shows the track, artist, and album currently playing (or paused) on Spotify. Requires a one-time OAuth token setup through the Spotify Developer portal.

| Config key | Type | Default | Description |
|---|---|---|---|
| `client_id` | string | *(required)* | Spotify app Client ID |
| `client_secret` | password | *(required)* | Spotify app Client Secret |
| `refresh_token` | password | *(required)* | Long-lived OAuth refresh token |
| `refresh_seconds` | number | `10` | Playback state poll cadence |

**Layouts:** full

---

### System Status (`system_status`)
A diagnostics dashboard showing Pi health metrics in a card grid: CPU temperature & load, RAM usage, disk usage, uptime, and local IP. A warning icon appears on the CPU temp card if it exceeds a configurable threshold.

| Config key | Type | Default | Description |
|---|---|---|---|
| `refresh_seconds` | number | `60` | Stats collection cadence |
| `show_ip` | toggle | `true` | Include the local IP address card |
| `cpu_temp_warn_celsius` | number | `70` | Temperature threshold for the warning indicator |

**Layouts:** full

---

## Hardware

Designed for the **Raspberry Pi Zero 2 W**, but runs on any Pi with GPIO headers.

**Recommended parts:**
- Raspberry Pi Zero 2 W (with pre-soldered headers)
- Waveshare 7.5" E-Ink Display V2
- 3× momentary push buttons

**Default GPIO pinout:**

| Function | GPIO |
|---|---|
| Button 1 — Prev | 17 |
| Button 2 — Action | 27 |
| Button 3 — Next | 22 |
| E-Ink RST | 5 |
| E-Ink DC | 25 |
| E-Ink BUSY | 24 |
| E-Ink SPI (CLK/MOSI/CS) | Standard SPI0 |

All pins are configurable in `config.yml`.

---

## Installation

### 1. Prepare your Pi

This section walks through everything from a blank SD card to a Pi that is online and ready for the install script. If you have already done this before, skip ahead to [step 2](#2-clone-and-run-the-install-script).

---

#### What you will need

- A **microSD card** (8 GB minimum, 16 GB+ recommended) and a way to plug it into your computer (a USB card reader works)
- A **Raspberry Pi** (Zero 2 W recommended) with a power supply
- Your **Wi-Fi network name (SSID) and password**
- A computer (Windows, Mac, or Linux)

---

#### Step 1 — Download Raspberry Pi Imager

Raspberry Pi Imager is the official free tool for writing the operating system to your SD card.

Download it from: **https://www.raspberrypi.com/software/**

Install it like any other application and open it.

---

#### Step 2 — Flash the SD card

1. Insert your microSD card into your computer.

2. Open **Raspberry Pi Imager** and click **Choose Device**. Select your Pi model (e.g. *Raspberry Pi Zero 2 W*).

3. Click **Choose OS**. Select:
   > **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (32-bit)**
   >
   > *"Lite" means no desktop — that is correct. The display runs headlessly.*

4. Click **Choose Storage** and select your SD card. Double-check it is the right drive before continuing.

5. Click **Next**. Imager will ask:
   > *"Would you like to apply OS customisation settings?"*

   Click **Edit Settings**. This is where you configure Wi-Fi and SSH **before** the first boot — no keyboard or monitor needed.

---

#### Step 3 — Configure Wi-Fi and SSH in Imager

In the **General** tab:
- ✅ **Set hostname** — give your Pi a name, e.g. `display`. You will use this to find it on your network later.
- ✅ **Set username and password** — choose a username (e.g. `pi`) and a strong password. **Write these down.**
- ✅ **Configure wireless LAN** — enter your Wi-Fi network name (SSID) and password exactly as they appear. Make sure the country code matches yours (e.g. `US`, `GB`).
- ✅ **Set locale settings** — set your timezone and keyboard layout.

In the **Services** tab:
- ✅ **Enable SSH** → select *Use password authentication*

Click **Save**, then **Yes** to apply the settings, then **Yes** to confirm writing the card.

> ⚠️ **This will erase everything on the SD card.** Make sure there is nothing important on it.

Wait for Imager to finish writing and verifying. When it says "Write Successful", eject the card.

---

#### Step 4 — Boot the Pi

1. Insert the microSD card into your Pi.
2. Plug in the power supply.
3. Wait **60–90 seconds** for first boot. The Pi is expanding the filesystem and connecting to Wi-Fi in the background — there is no screen feedback, so just wait.

---

#### Step 5 — Find your Pi's IP address

You need the Pi's IP address to connect to it. Try these options in order:

**Option A — Use the hostname (easiest)**

On most home networks, you can reach the Pi by its hostname directly. If you set the hostname to `display` in step 3, try:

```bash
ping display.local
```

If it replies, note the IP address shown in the output (e.g. `192.168.1.42`). You can skip to step 6.

**Option B — Check your router**

Log into your router's admin page (usually `http://192.168.1.1` or `http://192.168.0.1` — check the label on your router). Look for a "Connected Devices" or "DHCP Clients" list and find an entry matching your Pi's hostname.

**Option C — Network scanner**

Download a free app like **Angry IP Scanner** (Windows/Mac/Linux) or **Fing** (iOS/Android), scan your network, and look for a device with a hostname containing "raspberry" or the name you chose.

---

#### Step 6 — Connect via SSH

SSH lets you type commands on your Pi from your computer's terminal.

**On Mac or Linux** — open the Terminal app and run:
```bash
ssh pi@display.local
```
Replace `pi` with your username and `display.local` with your Pi's hostname or IP address. Type `yes` when asked about the fingerprint, then enter your password.

**On Windows** — open **PowerShell** or **Windows Terminal** (both come pre-installed on Windows 10/11) and run the same command:
```powershell
ssh pi@display.local
```
Alternatively, download [PuTTY](https://www.putty.org/) if you prefer a GUI. Enter your Pi's IP address or hostname and click Open.

---

Once you see the Pi's command prompt (something like `pi@display:~ $`), you are connected and ready for the next step.

### 2. Clone and run the install script
```bash
git clone https://github.com/mykalstark/dumb-smart-display.git
cd dumb-smart-display
./scripts/install.sh
```

The install script:
- Installs system packages (`python3`, `python3-venv`, `python3-pil`, SPI/GPIO libs, DejaVu fonts)
- Enables the SPI interface via `raspi-config`
- Downloads the Waveshare e-Paper Python library (sparse checkout)
- Creates a Python virtualenv and installs all Python dependencies
- Installs and enables two `systemd` services that start at boot
- Writes a `sudoers` rule so the web UI can restart both services without a password prompt

### 3. Open the Web UI
Once the install completes, open a browser on any device on the same network:

```
http://<your-pi-ip>:8080
```

From the Web UI you can configure every setting, enable modules, and apply updates — no SSH or file editing required.

---

## Configuration

### Via the Web UI *(recommended)*

The Web UI at `http://<pi-ip>:8080` provides a full settings editor covering:

- **Location** — Latitude, longitude, location name, temperature unit (shared by Clock and Weather Forecast)
- **Active Modules** — Toggle any module on or off with a single click
- **Module Settings** — Expandable settings panel for each module
- **Display Settings** — Screen rotation, module cycle interval, simulator mode
- **Web UI Settings** — Optional password protection, listen port

Saving applies the new config and restarts the display service automatically.

### Via YAML *(advanced / headless)*

If you prefer direct file editing:

```bash
cp config/config.example.yml config/config.yml
nano config/config.yml
sudo systemctl restart dumb-smart-display
```

The config file is well-commented. Key sections:

```yaml
location:
  latitude: 40.5132
  longitude: -112.3214
  temperature_unit: "fahrenheit"   # or "celsius"
  location_name: "Home"

hardware:
  simulate: false          # true = render to terminal, no screen required
  rotation: 0              # 0 / 90 / 180 / 270
  driver: "epd7in5_V2"     # pre-Sep 2023 800x480 panels should use epd7in5_V2_old
  spi_hz: 4000000          # lower to 2000000 or 1000000 for signal-integrity issues
  cycle_seconds: 30        # how long each module stays on screen
  after_hours:
    enabled: false
    start: "22:00"
    end: "07:00"
    render_mode: "1bit_floyd"  # use 1-bit modes on older 2-gray panels

modules:
  enabled:
    - clock
    - weather_forecast
    - calendar_ics
  settings:
    calendar_ics:
      ics_url: "https://calendar.google.com/calendar/ical/..."
      refresh_seconds: 900
    weather_forecast:
      refresh_seconds: 3600
```

---

## Updating

### Via the Web UI *(easiest)*
Open the Web UI → **Software** card → **Update & Restart**.

A progress modal streams live output as the updater:
1. Fetches and lists new commits from GitHub
2. Pulls the latest code (`git pull --ff-only origin main`)
3. Runs the install script to pick up any new system or Python dependencies
4. Restarts both services and auto-refreshes the page

### Via SSH
```bash
git pull
sudo systemctl restart dumb-smart-display
sudo systemctl restart dumb-smart-display-webui
```

---

## Service Management

Two `systemd` services run the project:

| Service | Purpose | Command |
|---|---|---|
| `dumb-smart-display` | Renders modules to the e-ink screen | `sudo systemctl restart dumb-smart-display` |
| `dumb-smart-display-webui` | Hosts the browser configuration UI | `sudo systemctl restart dumb-smart-display-webui` |

**View logs:**
```bash
# Display service
journalctl -u dumb-smart-display -f

# Web UI service
journalctl -u dumb-smart-display-webui -f
```

---

## Architecture & Development

```
/app
  /core           # ModuleManager, Module Interface, Layout definitions
  /modules        # Content modules (one file per module)
  /webui          # Flask configuration UI (server.py, templates/, schema.py)
  buttons.py      # GPIO button handling
  display.py      # Display driver abstraction (hardware vs. simulator)
  main.py         # Entry point
/config           # User configuration (config.yml) and example
/scripts          # install.sh, dev helpers, display test
/systemd          # Service unit templates
/docs             # Module API reference
```

### Running the Simulator

You don't need a Pi to develop modules. The simulator renders to your terminal:

```bash
./scripts/dev_simulate.sh
```

This automatically creates a local venv and installs all dependencies.

### Running the Web UI Locally

```bash
./scripts/dev_webui.sh
```

Then open `http://localhost:8080`.

### Writing a New Module

All modules implement the `BaseDisplayModule` protocol defined in `app/core/module_interface.py`.

Key methods:

| Method | Required | Description |
|---|---|---|
| `render(width, height, **kwargs)` | ✅ | Return a `PIL.Image` to display |
| `tick()` | ✅ | Called periodically for background work (data fetching, etc.) |
| `handle_button(event)` | ✅ | React to `"prev"`, `"next"`, `"action"`, `"refresh"` button events |
| `refresh_interval()` | optional | Return seconds between automatic re-renders, or `None` |
| `supported_layouts()` | optional | Return a tuple of `LayoutPreset` objects (default: full only) |

See [`docs/module_api.md`](docs/module_api.md) for the full API reference and layout preset definitions.

---

## Troubleshooting

**Screen not updating:**
```bash
journalctl -u dumb-smart-display -f
```

**Test display hardware directly:**
```bash
./scripts/display_test.sh
```

**Diagnose banding / column artifacts:**
```bash
python3 scripts/panel_diagnostics.py --pause 8
python3 scripts/panel_diagnostics.py --spi-hz 2000000 --pause 8
```

**Web UI not reachable:**
```bash
journalctl -u dumb-smart-display-webui -f
# Check what port it's listening on
sudo ss -tlnp | grep python
```

**TickTick or Mealie not connecting:**
Check that your access token is correct and the service is reachable from the Pi. The Web UI will show any error messages the module reports when it fails to fetch data.
