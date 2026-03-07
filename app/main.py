# app/main.py
#!/usr/bin/env python3

import argparse
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps  # <--- Need this to load fonts

from app.buttons import init_buttons
from app.core.module_manager import ModuleManager
from app.display import Display


DEFAULT_CONFIG_PATH = Path("config/config.yml")
DEFAULT_CONFIG_FALLBACK = Path("config/config.example.yml")
_UPLOADS_DIR = Path(__file__).parent / "webui" / "static" / "uploads"
_AFTER_HOURS_RENDER_MODES = {"1bit_floyd", "1bit_bayer", "1bit_stochastic", "4gray"}
_BAYER_8X8 = (
    (0, 48, 12, 60, 3, 51, 15, 63),
    (32, 16, 44, 28, 35, 19, 47, 31),
    (8, 56, 4, 52, 11, 59, 7, 55),
    (40, 24, 36, 20, 43, 27, 39, 23),
    (2, 50, 14, 62, 1, 49, 13, 61),
    (34, 18, 46, 30, 33, 17, 45, 29),
    (10, 58, 6, 54, 9, 57, 5, 53),
    (42, 26, 38, 22, 41, 25, 37, 21),
)


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
    spi_hz = hardware_cfg.get("spi_hz")
    pins_cfg = hardware_cfg.get("pins") or {}
    pin_config = {key: int(value) for key, value in pins_cfg.items()}
    return Display(
        simulate=simulate,
        rotation=rotation,
        driver_name=driver_name,
        library_path=library_path,
        pin_config=pin_config,
        spi_hz=int(spi_hz) if spi_hz else None,
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


def _normalize_after_hours_render_mode(raw_mode: Any) -> str:
    mode = str(raw_mode or "1bit_floyd").strip().lower()
    return mode if mode in _AFTER_HOURS_RENDER_MODES else "1bit_floyd"


def _prepare_after_hours_source(
    photo_path: Path,
    width: int,
    height: int,
    render_mode: str = "1bit_floyd",
) -> Image.Image:
    # Normalize EXIF orientation first so phone photos land correctly on-panel.
    raw = ImageOps.exif_transpose(Image.open(photo_path)).convert("L")
    raw = ImageOps.fit(raw, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
    raw = ImageOps.autocontrast(raw, cutoff=1 if render_mode in {"4gray", "1bit_stochastic"} else 2)

    if render_mode == "4gray":
        gamma = 0.92
        contrast = 1.18
        sharpness = 1.45
        blur_radius = 0.0
    elif render_mode == "1bit_stochastic":
        gamma = 1.02
        contrast = 1.12
        sharpness = 1.05
        blur_radius = 0.65
    else:
        gamma = 1.35
        contrast = 1.35
        sharpness = 1.8
        blur_radius = 0.0

    gamma_lut = [int(((i / 255.0) ** gamma) * 255.0) for i in range(256)]
    raw = raw.point(gamma_lut)
    if blur_radius > 0.0:
        raw = raw.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    raw = ImageEnhance.Contrast(raw).enhance(contrast)
    raw = ImageEnhance.Sharpness(raw).enhance(sharpness)
    return raw


def _ordered_dither_1bit(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    out = Image.new("1", gray.size, 255)
    src = gray.load()
    dst = out.load()

    # Ordered dithering is less directional than Floyd-Steinberg and can
    # reduce visible streaking on photos with smooth gradients.
    for y in range(gray.height):
        row = _BAYER_8X8[y & 7]
        for x in range(gray.width):
            threshold = ((row[x & 7] + 0.5) * 255.0) / 64.0
            dst[x, y] = 0 if src[x, y] < threshold else 255

    return out


def _stochastic_dither_1bit(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    out = Image.new("1", gray.size, 255)
    src = gray.load()
    dst = out.load()

    # Add deterministic midtone noise before thresholding. On 2-gray panels this
    # often breaks up long smooth contours that otherwise show up as visible bands.
    for y in range(gray.height):
        for x in range(gray.width):
            px = src[x, y]
            seed = (x * 374761393 + y * 668265263 + 0x9E3779B9) & 0xFFFFFFFF
            seed ^= seed >> 13
            seed = (seed * 1274126177) & 0xFFFFFFFF
            noise = (((seed >> 24) & 0xFF) - 127.5) / 127.5
            midtone_weight = 1.0 - abs(px - 127.5) / 127.5
            threshold = 127.5 + noise * 26.0 * max(midtone_weight, 0.0)
            dst[x, y] = 0 if px < threshold else 255

    return out


def _select_best_monochrome_variant(
    raw: Image.Image,
    converter: Callable[[Image.Image], Image.Image],
) -> Tuple[Image.Image, float, float]:
    target_black_ratio = 0.36
    best_image = None
    best_score = float("inf")
    best_ratio = 0.0
    best_brightness = 1.0

    for brightness in (1.0, 0.92, 0.85, 0.78):
        toned = ImageEnhance.Brightness(raw).enhance(brightness)
        candidate = converter(toned)
        hist = candidate.histogram()
        black_ratio = hist[0] / max(candidate.width * candidate.height, 1)
        score = abs(black_ratio - target_black_ratio)
        if black_ratio < 0.28:
            score += 0.15
        if score < best_score:
            best_score = score
            best_image = candidate
            best_ratio = black_ratio
            best_brightness = brightness

    if best_image is None:
        raise RuntimeError("Failed to prepare after-hours photo")

    return best_image, best_ratio, best_brightness


def _quantize_4gray(image: Image.Image) -> Image.Image:
    return image.convert("L").point(
        # Waveshare's 4-gray driver expects GRAY4/3/2/1 = 0x00/0x80/0xC0/0xFF.
        lambda x: 0x00 if x < 64 else 0x80 if x < 128 else 0xC0 if x < 192 else 0xFF,
        "L",
    )


def _select_best_four_gray_variant(raw: Image.Image) -> Tuple[Image.Image, float, float, float]:
    target_mean_luma = 182.0
    best_image = None
    best_score = float("inf")
    best_mean = 0.0
    best_brightness = 1.0
    best_white_ratio = 0.0
    total_pixels = max(raw.width * raw.height, 1)

    for brightness in (1.0, 1.08, 1.16, 1.24, 1.32):
        toned = ImageEnhance.Brightness(raw).enhance(brightness)
        candidate = _quantize_4gray(toned)
        hist = candidate.histogram()
        black_count = hist[0]
        dark_gray_count = hist[0x80]
        light_gray_count = hist[0xC0]
        white_count = hist[0xFF]
        mean_luma = (
            (0 * black_count)
            + (128 * dark_gray_count)
            + (192 * light_gray_count)
            + (255 * white_count)
        ) / total_pixels
        white_ratio = white_count / total_pixels
        black_ratio = black_count / total_pixels
        score = abs(mean_luma - target_mean_luma) / 255.0
        if white_ratio < 0.18:
            score += 0.08
        if black_ratio > 0.18:
            score += 0.08
        if score < best_score:
            best_score = score
            best_image = candidate
            best_mean = mean_luma
            best_brightness = brightness
            best_white_ratio = white_ratio

    if best_image is None:
        raise RuntimeError("Failed to prepare 4-gray after-hours photo")

    return best_image, best_mean, best_brightness, best_white_ratio


def _render_after_hours(display: "Display", config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    """Render the after hours screen once (photo or fallback message)."""
    ah_cfg = config.get("hardware", {}).get("after_hours", {})
    photo_name = ah_cfg.get("photo", "")
    requested_mode = _normalize_after_hours_render_mode(ah_cfg.get("render_mode"))
    render_mode = requested_mode
    w, h = display.driver.width, display.driver.height
    image = None

    if photo_name:
        photo_path = _UPLOADS_DIR / photo_name
        try:
            if render_mode == "4gray" and not display.supports_four_gray():
                print(
                    "[MAIN] 4-gray after hours mode requested, but the current "
                    "driver/panel does not expose 4-gray support. Falling back to 1bit_floyd.",
                    flush=True,
                )
                render_mode = "1bit_floyd"

            if render_mode == "4gray":
                raw = _prepare_after_hours_source(photo_path, w, h, render_mode="4gray")
                image, mean_luma, best_brightness, white_ratio = _select_best_four_gray_variant(raw)
                print(
                    "[MAIN] After hours photo prepared in 4-gray mode "
                    f"(mean_luma={mean_luma:.1f}, brightness={best_brightness:.2f}, white_ratio={white_ratio:.3f}).",
                    flush=True,
                )
            else:
                raw = _prepare_after_hours_source(photo_path, w, h, render_mode=render_mode)
                converter: Callable[[Image.Image], Image.Image]
                if render_mode == "1bit_bayer":
                    converter = _ordered_dither_1bit
                elif render_mode == "1bit_stochastic":
                    converter = _stochastic_dither_1bit
                else:
                    converter = lambda toned: toned.convert("1", dither=Image.FLOYDSTEINBERG)

                image, best_ratio, best_brightness = _select_best_monochrome_variant(raw, converter)
                print(
                    "[MAIN] After hours photo prepared successfully "
                    f"(mode={render_mode}, black_ratio={best_ratio:.3f}, brightness={best_brightness:.2f}).",
                    flush=True,
                )
        except Exception as exc:
            print(f"[MAIN] After hours photo load failed: {exc}", flush=True)

    if image is None:
        # Fallback: plain white canvas with a centred status message.
        image = Image.new("1", (w, h), 255)
        draw = ImageDraw.Draw(image)
        font = fonts.get("default")
        lines = ["After Hours", "No photo configured"]
        line_h = draw.textbbox((0, 0), lines[0], font=font)[3]
        total_h = line_h * len(lines) + 8 * (len(lines) - 1)
        y = (h - total_h) // 2
        for line in lines:
            tw = draw.textbbox((0, 0), line, font=font)[2]
            draw.text(((w - tw) // 2, y), line, font=font, fill=0)
            y += line_h + 8

    # Use the dedicated photo path so the image stays full-bleed.
    # render() always calls _add_border(), which is correct for UI screens
    # but adds an unwanted decorative frame around photos.
    actual_mode = display.render_photo(image, mode=render_mode)
    print(f"[MAIN] After hours photo rendered with mode={actual_mode}.", flush=True)


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

    max_cycles = args.cycles
    cycle_count = 0
    _after_hours_rendered = False

    print(f"[MAIN] Cycle delay: {cycle_delay}s.", flush=True)

    try:
        while True:
            # 1. Check After Hours
            ah_cfg = config.get("hardware", {}).get("after_hours", {})
            is_after_hours = False
            if ah_cfg.get("enabled", False):
                ah_start = ah_cfg.get("start", "")
                ah_end   = ah_cfg.get("end", "")
                if ah_start and ah_end:
                    current_time = datetime.now().strftime("%H:%M")
                    if ah_start > ah_end:   # crosses midnight
                        is_after_hours = current_time >= ah_start or current_time < ah_end
                    else:
                        is_after_hours = ah_start <= current_time < ah_end

            if is_after_hours:
                if not _after_hours_rendered:
                    _render_after_hours(display, config, fonts)
                    _after_hours_rendered = True
                time.sleep(60)
                continue

            _after_hours_rendered = False  # reset when we exit the after hours window

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
