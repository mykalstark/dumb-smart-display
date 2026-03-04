# app/main.py
#!/usr/bin/env python3

import argparse
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml
from PIL import ImageFont  # <--- Need this to load fonts

from app.buttons import init_buttons
from app.core.module_manager import ModuleManager
from app.display import Display


DEFAULT_CONFIG_PATH = Path("config/config.yml")
DEFAULT_CONFIG_FALLBACK = Path("config/config.example.yml")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Rules:
    - If both values are dicts, recurse so nested keys are merged individually.
    - For all other types (including lists), the override value wins outright.

    This means ``modules.enabled`` (a list) is fully replaced by the user's
    version, while ``modules.settings`` (a dict) is merged key-by-key so that
    new module sections added to the example automatically appear with their
    default values without touching the user's existing settings.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    # Always load the example file first as a baseline of defaults.
    base: Dict[str, Any] = {}
    if DEFAULT_CONFIG_FALLBACK.exists():
        with DEFAULT_CONFIG_FALLBACK.open("r", encoding="utf-8") as handle:
            base = yaml.safe_load(handle) or {}

    if not path.exists():
        if base:
            print(
                f"[MAIN] config/config.yml not found — using {DEFAULT_CONFIG_FALLBACK} as defaults. "
                "Copy it to config/config.yml and fill in your settings."
            )
        else:
            print("[MAIN] No configuration found. Using defaults.")
        return base

    with path.open("r", encoding="utf-8") as handle:
        user_cfg = yaml.safe_load(handle) or {}

    # Deep-merge: user values win; new keys from the example fill in automatically.
    merged = _deep_merge(base, user_cfg)
    return merged

# <--- NEW HELPER: Load Fonts
def load_fonts() -> Dict[str, Any]:
    fonts = {}
    try:
        # Adjust paths/sizes as you like
        fonts["default"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        fonts["large"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        fonts["small"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except IOError:
        print("[MAIN] Warning: Could not load TrueType fonts. Using default bitmap font.")
        default = ImageFont.load_default()
        fonts = {"default": default, "large": default, "small": default}
    return fonts

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Dumb Smart Display.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="Path to YAML configuration file.")
    parser.add_argument("--simulate", action="store_true", help="Force simulator mode regardless of config.")
    parser.add_argument("--cycles", type=int, default=0, help="Number of render cycles before exiting (0 = infinite).")
    return parser.parse_args()


def build_display(config: Dict[str, Any], force_simulate: bool) -> Display:
    hardware_cfg = config.get("hardware", {})
    simulate = force_simulate or hardware_cfg.get("simulate", True)
    rotation = int(hardware_cfg.get("rotation", 0))
    driver_name = hardware_cfg.get("driver", "epd7in5_V2")
    library_path = hardware_cfg.get("library_path")
    pins_cfg = hardware_cfg.get("pins") or {}
    pin_config = {key: int(value) for key, value in pins_cfg.items()}
    return Display(
        simulate=simulate,
        rotation=rotation,
        driver_name=driver_name,
        library_path=library_path,
        pin_config=pin_config,
    )

# <--- UPDATED: Accepts fonts
def build_module_manager(config: Dict[str, Any], fonts: Dict[str, Any]) -> ModuleManager:
    modules_cfg = config.get("modules", {})
    enabled_modules = modules_cfg.get("enabled")
    module_config = modules_cfg.get("settings", {})

    # Inject top-level shared config (e.g. location) into every module's settings.
    # Module-specific keys always win — shared values only fill in the gaps.
    shared: Dict[str, Any] = {}
    location = config.get("location", {})
    if isinstance(location, dict):
        shared.update(location)

    # Resolve shorthand time-format tokens to strftime strings so all modules
    # receive a ready-to-use format string regardless of which token was stored.
    _TIME_FORMATS: Dict[str, str] = {"12h": "%I:%M %p", "24h": "%H:%M"}
    if "time_format" in shared:
        shared["time_format"] = _TIME_FORMATS.get(shared["time_format"], shared["time_format"])

    if shared:
        all_names = list(enabled_modules or []) + list(module_config.keys())
        for name in dict.fromkeys(all_names):  # deduplicated, insertion order preserved
            module_config[name] = {**shared, **module_config.get(name, {})}

    # Pass fonts to manager
    manager = ModuleManager(fonts=fonts, enabled_modules=enabled_modules, module_config=module_config)
    manager.load_modules()
    return manager


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)

    # 1. Load Fonts
    fonts = load_fonts()

    print("[MAIN] Dumb Smart Display starting...", flush=True)
    # 2. Pass fonts to manager
    manager = build_module_manager(config, fonts)

    display = build_display(config, force_simulate=args.simulate)
    
    # Event to wake the main loop for immediate updates
    wake_event = threading.Event()
    
    # State to track if the next render should be a full refresh
    next_render_force_full = False

    def render_active_module() -> None:
        nonlocal next_render_force_full
        module = manager.current_module()
        if module is None:
            display.render_text("No modules enabled.")
            return

        try:
            w = display.driver.width
            h = display.driver.height
            content = module.render(width=w, height=h)
            
            # Render with the force flag if set
            display.render(content, force_full_refresh=next_render_force_full)
            
            # Reset flag after rendering
            if next_render_force_full:
                next_render_force_full = False
                
        except Exception as exc:
            print(f"[MAIN] Error rendering module {module}: {exc}", flush=True)

    def on_button(event: str) -> None:
        nonlocal next_render_force_full
        # Handle state change immediately, then wake the loop to render
        manager.route_button_event(event)
        
        if event == "refresh":
            next_render_force_full = True
            
        wake_event.set()

    init_buttons(display, simulate=display.simulate, on_event=on_button)

    cycle_delay = int(config.get("hardware", {}).get("cycle_seconds", 30))
    
    # Quiet Hours Config
    quiet_cfg = config.get("hardware", {}).get("quiet_hours", {})
    quiet_start_str = quiet_cfg.get("start")
    quiet_end_str = quiet_cfg.get("end")

    max_cycles = args.cycles
    cycle_count = 0

    print(f"[MAIN] Cycle delay: {cycle_delay}s. Quiet hours: {quiet_start_str}-{quiet_end_str}")

    try:
        while True:
            # 1. Check Quiet Hours
            is_quiet = False
            if quiet_start_str and quiet_end_str:
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                
                # Handle range crossing midnight (e.g. 22:00 to 06:00)
                if quiet_start_str > quiet_end_str:
                    if current_time >= quiet_start_str or current_time < quiet_end_str:
                        is_quiet = True
                else:
                    if quiet_start_str <= current_time < quiet_end_str:
                        is_quiet = True

            if is_quiet:
                # Sleep and retry. We use sleep instead of wait here to save resources,
                # effectively ignoring buttons during quiet hours (unless we wanted to wake).
                time.sleep(60)
                continue

            # 2. Render
            render_active_module()

            # 3. Background Ticks
            manager.tick_modules()
            
            # 4. Check Exit Condition
            cycle_count += 1
            if max_cycles and cycle_count >= max_cycles:
                print("[MAIN] Completed requested render cycles. Exiting.")
                break

            # 5. Wait for Delay OR Event
            # wait returns True if the flag was set (button pressed), False on timeout
            signaled = wake_event.wait(timeout=cycle_delay)
            
            if signaled:
                # Button was pressed. State has already changed in on_button.
                # Clear the event so we can wait again next time.
                wake_event.clear()
                # We skip activate_next() because the user likely navigated manually.
            else:
                # Timeout occurred: Auto-advance to next module
                manager.activate_next()

    except KeyboardInterrupt:
        print("[MAIN] Exiting...")


if __name__ == "__main__":
    main()