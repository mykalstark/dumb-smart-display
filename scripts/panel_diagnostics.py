#!/usr/bin/env python3
"""Exercise the panel with high-signal diagnostic patterns.

Run this on the Pi to distinguish image-processing artifacts from
panel/power/SPI issues:

  python3 scripts/panel_diagnostics.py --pause 8
  python3 scripts/panel_diagnostics.py --spi-hz 2000000 --pause 8
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    _UPLOADS_DIR,
    _ordered_dither_1bit,
    _prepare_after_hours_source,
    _quantize_4gray,
    _select_best_four_gray_variant,
    _stochastic_dither_1bit,
    build_display,
    load_config,
)


PatternSpec = Tuple[str, Callable[[int, int], Image.Image], str]


def _solid(value: int) -> Callable[[int, int], Image.Image]:
    def factory(width: int, height: int) -> Image.Image:
        return Image.new("1", (width, height), value)

    return factory


def _vertical_stripes(width_px: int = 1) -> Callable[[int, int], Image.Image]:
    def factory(width: int, height: int) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        pixels = image.load()
        for x in range(width):
            color = 0 if ((x // width_px) % 2 == 0) else 255
            for y in range(height):
                pixels[x, y] = color
        return image

    return factory


def _horizontal_stripes(height_px: int = 1) -> Callable[[int, int], Image.Image]:
    def factory(width: int, height: int) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        pixels = image.load()
        for y in range(height):
            color = 0 if ((y // height_px) % 2 == 0) else 255
            for x in range(width):
                pixels[x, y] = color
        return image

    return factory


def _checkerboard(block: int = 8) -> Callable[[int, int], Image.Image]:
    def factory(width: int, height: int) -> Image.Image:
        image = Image.new("1", (width, height), 255)
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                color = 0 if (((x // block) + (y // block)) % 2 == 0) else 255
                pixels[x, y] = color
        return image

    return factory


def _horizontal_gradient(width: int, height: int) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    pixels = image.load()
    for x in range(width):
        value = int((x / max(width - 1, 1)) * 255)
        for y in range(height):
            pixels[x, y] = value
    return image


def _photo_path_from_config(config_path: Path) -> Optional[Path]:
    cfg = load_config(config_path)
    photo_name = cfg.get("hardware", {}).get("after_hours", {}).get("photo", "")
    if not photo_name:
        return None
    photo_path = _UPLOADS_DIR / photo_name
    return photo_path if photo_path.exists() else None


def _gradient_floyd(width: int, height: int) -> Image.Image:
    return _horizontal_gradient(width, height).convert("1", dither=Image.FLOYDSTEINBERG)


def _gradient_bayer(width: int, height: int) -> Image.Image:
    return _ordered_dither_1bit(_horizontal_gradient(width, height))


def _gradient_4gray(width: int, height: int) -> Image.Image:
    return _quantize_4gray(_horizontal_gradient(width, height))


def _photo_factory(photo_path: Path, mode: str) -> Callable[[int, int], Image.Image]:
    def factory(width: int, height: int) -> Image.Image:
        prepared = _prepare_after_hours_source(photo_path, width, height, render_mode=mode)
        if mode == "4gray":
            image, _, _, _ = _select_best_four_gray_variant(prepared)
            return image
        if mode == "1bit_bayer":
            return _ordered_dither_1bit(prepared)
        if mode == "1bit_stochastic":
            return _stochastic_dither_1bit(prepared)
        return prepared.convert("1", dither=Image.FLOYDSTEINBERG)

    return factory


def _build_patterns(photo_path: Optional[Path], supports_four_gray: bool) -> List[PatternSpec]:
    patterns: List[PatternSpec] = [
        ("solid-white", _solid(255), "1bit_floyd"),
        ("solid-black", _solid(0), "1bit_floyd"),
        ("vertical-stripes-1px", _vertical_stripes(1), "1bit_floyd"),
        ("vertical-stripes-8px", _vertical_stripes(8), "1bit_floyd"),
        ("horizontal-stripes-1px", _horizontal_stripes(1), "1bit_floyd"),
        ("checkerboard-8px", _checkerboard(8), "1bit_floyd"),
        ("gradient-floyd", _gradient_floyd, "1bit_floyd"),
        ("gradient-bayer", _gradient_bayer, "1bit_bayer"),
        ("gradient-stochastic", lambda w, h: _stochastic_dither_1bit(_horizontal_gradient(w, h)), "1bit_stochastic"),
    ]

    if supports_four_gray:
        patterns.append(("gradient-4gray", _gradient_4gray, "4gray"))

    if photo_path:
        patterns.append(("photo-floyd", _photo_factory(photo_path, "1bit_floyd"), "1bit_floyd"))
        patterns.append(("photo-bayer", _photo_factory(photo_path, "1bit_bayer"), "1bit_bayer"))
        patterns.append(("photo-stochastic", _photo_factory(photo_path, "1bit_stochastic"), "1bit_stochastic"))
        if supports_four_gray:
            patterns.append(("photo-4gray", _photo_factory(photo_path, "4gray"), "4gray"))

    return patterns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render diagnostic patterns to the e-paper panel.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to config.yml")
    parser.add_argument("--pause", type=int, default=8, help="Seconds to hold each pattern on screen")
    parser.add_argument("--photo", type=Path, help="Optional explicit photo path to test")
    parser.add_argument("--driver", help="Optional driver override, e.g. epd7in5_V2_old")
    parser.add_argument("--spi-hz", type=int, help="Optional SPI speed override for this run")
    parser.add_argument("--simulate", action="store_true", help="Force simulator mode")
    parser.add_argument(
        "--patterns",
        nargs="+",
        help="Optional subset of pattern names to run. Defaults to the full sequence.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.driver:
        config.setdefault("hardware", {})["driver"] = args.driver
    if args.spi_hz:
        config.setdefault("hardware", {})["spi_hz"] = args.spi_hz

    display = build_display(config, force_simulate=args.simulate)
    width = display.driver.width
    height = display.driver.height
    supports_four_gray = display.supports_four_gray()

    photo_path = args.photo or _photo_path_from_config(args.config)
    if photo_path is not None:
        photo_path = photo_path.expanduser().resolve()
        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

    patterns = _build_patterns(photo_path, supports_four_gray)
    if args.patterns:
        wanted = set(args.patterns)
        patterns = [pattern for pattern in patterns if pattern[0] in wanted]
        if not patterns:
            raise ValueError("No matching patterns selected.")

    print(f"[DIAG] Display size: {width}x{height}")
    print(f"[DIAG] 4-gray support: {supports_four_gray}")
    if photo_path:
        print(f"[DIAG] Photo source: {photo_path}")
    print(f"[DIAG] Pause between patterns: {args.pause}s")

    for name, factory, mode in patterns:
        print(f"[DIAG] Rendering {name} (mode={mode})")
        image = factory(width, height)
        display.render_photo(image, mode=mode)
        time.sleep(args.pause)

    print("[DIAG] Sequence complete.")


if __name__ == "__main__":
    main()
