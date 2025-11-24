# **Dumb Smart Display – Project Overview**

**Dumb Smart Display** is a modular Raspberry Pi–powered information display meant to act like a “smart screen” without the ecosystem lock-in, data harvesting, or cloud dependency of commercial devices. Everything is open-source, local-only, and designed for easy customization.

The project combines:

* A Raspberry Pi Zero 2 W
* A small e-ink or LCD display
* Three physical buttons wired to GPIO
* Open-source Python software
* A plug-in module system for features
* A 3D-printed case ecosystem that can look like anything—picture frame, CRT-style shell, themed housing, etc.

The goal is simple: **give users a small, always-on display that shows the info *they* want, how *they* want it, with zero cloud dependence.**

---

# **Core Concept**

At its heart, this is a **module-driven dashboard**.
Each “module” is a self-contained Python component that provides:

* Something to display
* Optional background tasks
* Optional user interaction via the buttons
* A render function for the screen

Examples of modules:

* Clock
* Weather
* Daily meal plan (via Mealie API)
* Calendar
* Task list
* Custom integrations
* Hobby dashboards
* Smart home sensors (local API)

Users can enable/disable modules through config files.

---

# **Hardware Summary**

* **Pi Zero 2 W** – brains of the system
* **E-ink or LCD screen** – main output
* **3 push buttons:**

  * Up → GPIO17
  * Select → GPIO27
  * Down → GPIO22
* **3D-printed enclosure** – customizable
* **Wi-Fi** for pulling modules, weather, etc.

The system is designed to survive unplug/replug without corruption, and eventually support auto-updating from GitHub.

---

# **Software Architecture**

```
/app
  /core
  /modules
  /drivers
/config
/scripts
/systemd
```

### **app/core/**

Core logic for:

* Module loading
* Screen update scheduling
* Button event handling
* System state
* Logging and error recovery

### **app/modules/**

Each folder = one module
Modules expose a consistent interface:

```python
class Module:
    def render() -> Image
    def on_button_press(button): optional
    def tick(): optional background logic
```

### **app/drivers/**

Hardware abstraction:

* Display driver (Waveshare/etc.)
* Button driver (GPIO)
* Simulator driver for PC development (no hardware required)

### **config/**

Configuration files defining:

* Which modules are enabled
* Hardware settings
* Rotation
* API keys
* Update preferences

### **scripts/**

Utility scripts:

* Pi bootstrap
* Install systemd service
* Update-and-restart
* Debug helpers

### **systemd/**

A service file allowing the display to run at boot like a real appliance.

---

# **How Development Works**

### **1. Developing on a PC**

You can work on modules and UI without touching a Pi:

1. Create a Python venv
2. Install requirements
3. Run the app in **simulator mode** so the display renders to a window or logs instead of GPIO
4. Push to GitHub

The Pi can then pull the newest commit and restart.

---

### **2. Setting Up a New Pi (High-Level)**

A new Raspberry Pi only needs a one-time bootstrap:

1. Flash Raspberry Pi OS Lite
2. Connect to Wi-Fi
3. SSH in
4. Run the provided bootstrap script
5. The script:

   * Installs system dependencies
   * Sets up a Python venv
   * Clones the repo
   * Installs Python packages
   * Installs systemd service
   * Starts the display

After that, the Pi acts like a sealed appliance.

---

# **Goal for Contributors**

Anyone new to the project should understand three things:

1. **Modules are the heart of the system.**
   If you can write a Python module that returns an image, you can extend the display.

2. **The hardware is simple and abstracted.**
   All GPIO and display code is behind clean interfaces.

3. **Setup is automated.**
   A bootstrap script handles everything so nobody has to manually configure a Pi.