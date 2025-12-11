# Dumb Smart Display

**Dumb Smart Display** is a modular, Raspberry Pi-powered information dashboard designed to look great on E-Ink or LCD screens. It focuses on local control, simple Python modules, and zero-maintenance operation.

The project combines:
*   **Hardware**: Raspberry Pi Zero 2 W + Waveshare E-Ink Display + Physical Buttons.
*   **Software**: A Python-based engine that renders "Modules" to the screen.
*   **Philosophy**: Your data, your screen, no mandatory cloud ecosystem.

---

## Features

*   **Modular Design**: Enable/disable features via a simple YAML config.
*   **Plug-and-Play Installation**: Automated setup script for Raspberry Pi OS.
*   **Hardware Agnostic**: Supports Waveshare E-Ink displays (via SPI) and a built-in **Simulator** for developing on your PC.
*   **Extensible**: Write your own modules in Python using the standard PIL (Pillow) library.

---

## Included Modules

The following modules are built-in:

### 1. Clock (`clock`)
The default home screen.
*   **Features**: Large high-contrast time, date, and local weather (requires API key).
*   **Layouts**: Full screen.

### 2. Mealie Today (`mealie_today`)
Integrates with [Mealie](https://nightly.mealie.io/) (self-hosted recipe manager).
*   **Features**: Shows tonight's dinner plan, prep/cook times, and a "START KITCHEN TIMER BY..." recommendation to ensure dinner is ready on time.
*   **Configuration**: Requires your Mealie URL and API token.

### 3. TickTick (`ticktick`)
Integrates with [TickTick](https://ticktick.com/).
*   **Features**: Displays tasks for "Today" and "Tomorrow" side-by-side. Support for task lists and time-blocking.
*   **Configuration**: Requires a TickTick Open API access token.

---

## Hardware Setup

This project is designed for the **Raspberry Pi Zero 2 W**, but runs on any Pi.

**Recommended Hardware:**
*   **Pi**: Raspberry Pi Zero 2 W (headers pre-soldered recommended).
*   **Display**: Waveshare 7.5" E-Ink Display (Model V2 or similar).
*   **Inputs**: 3x Push Buttons wired to GPIO.

**Default Pinout (defined in `config.yml`):**
*   **BTN1 (Up/Prev)**: GPIO 17
*   **BTN2 (Select/Action)**: GPIO 27
*   **BTN3 (Down/Next)**: GPIO 22
*   **E-Ink SPI**: Standard SPI + Busy (24), RST (5), DC (25).

---

## Installation

### 1. Prepare your Pi
Flash **Raspberry Pi OS Lite** to your SD card. Connect to Wi-Fi and SSH in.

### 2. Install the Software
Run the following commands on your Pi:

```bash
git clone https://github.com/mykalstark/dumb-smart-display.git
cd dumb-smart-display
./scripts/install.sh
```

**What this does:**
*   Installs system dependencies (Python, SPI, GPIO).
*   Sets up a Python `venv` and installs packages.
*   Installs the Waveshare E-Paper drivers.
*   Sets up a `systemd` service so the display starts at boot.

### 3. Configure
Copy the example configuration to the live config file:

```bash
cp config/config.example.yml config/config.yml
nano config/config.yml
```

Edit `config.yml` to:
1.  Set `hardware.simulate: false` (to use the real screen).
2.  Enable the modules you want.
3.  Add your API tokens (Weather, Mealie, TickTick).

### 4. Restart Service
```bash
sudo systemctl restart dumb-smart-display
```

---

## Architecture & Development

The project is structured to separate the core engine from content modules.

```
/app
  /core         # ModuleManager, Module Interface, Layout definitions
  /modules      # Content providers (Clock, Mealie, etc.)
  buttons.py    # GPIO interaction
  display.py    # Display driver abstraction (Hardware vs Simulator)
  main.py       # Entry point
/config         # User configuration
/scripts        # Helpers for install/test/dev
```

### Developing on your PC (Simulator)

You don't need a Pi to write modules! The project includes a simulator that renders the display to your terminal (or a window, depending on configuration).

**Run the Simulator:**
```bash
./scripts/dev_simulate.sh
```
This script handles creating the local `venv` and installing dependencies automatically.

### Writing a New Module

Modules are Python classes that implement the **Module Protocol**.
See [`docs/module_api.md`](docs/module_api.md) for full documentation on:
*   `render(width, height)`: Draw your content.
*   `tick()`: Background updates.
*   `Layout Presets`: Defining how your module fits on the screen.

---

## Troubleshooting

**Logs**:
View logs via systemd:
```bash
journalctl -u dumb-smart-display -f
```

**Test Display Hardware**:
If the screen isn't working, run the low-level hardware test:
```bash
./scripts/display_test.sh
```

**Test API Connections**:
Verify your TickTick or Mealie connection without running the full app:
```bash
./scripts/test_ticktick_connection.py
```