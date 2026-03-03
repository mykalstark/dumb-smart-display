"""System status module — shows Pi health stats (CPU, RAM, disk, uptime, IP)."""
from __future__ import annotations

import logging
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset

log = logging.getLogger(__name__)

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    log.warning("psutil not installed. system_status module will show placeholder data.")


def _read_cpu_temp_linux() -> Optional[float]:
    """Read CPU temperature from the Linux thermal sysfs interface."""
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal.exists():
        try:
            return int(thermal.read_text().strip()) / 1000.0
        except Exception:
            pass
    return None


def _get_cpu_temp() -> Optional[float]:
    if not _PSUTIL_AVAILABLE:
        return _read_cpu_temp_linux()

    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return _read_cpu_temp_linux()
        # Raspberry Pi uses "cpu_thermal"; Intel/AMD uses "coretemp"
        for key in ("cpu_thermal", "coretemp", "k10temp", "acpitz"):
            if key in temps:
                entries = temps[key]
                if entries:
                    return entries[0].current
        # Fallback: first available sensor
        for entries in temps.values():
            if entries:
                return entries[0].current
    except Exception:
        pass

    return _read_cpu_temp_linux()


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "N/A"


def _format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _format_uptime(seconds: float) -> str:
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


class Module(BaseDisplayModule):
    name = "system_status"

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts

        self.refresh_seconds: int = int(self.config.get("refresh_seconds", 60))
        self.show_ip: bool = bool(self.config.get("show_ip", True))
        self.temp_warn: float = float(self.config.get("cpu_temp_warn_celsius", 70))

        self._stats: Dict[str, Any] = {}
        self._last_fetch: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return self.refresh_seconds

    def tick(self) -> None:
        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch).total_seconds() < self.refresh_seconds:
            return
        self._collect_stats()

    def handle_button(self, event: str) -> None:
        pass  # Display-only module

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------
    def _collect_stats(self) -> None:
        stats: Dict[str, Any] = {}

        # CPU temp
        stats["cpu_temp"] = _get_cpu_temp()

        if _PSUTIL_AVAILABLE:
            try:
                stats["cpu_pct"] = psutil.cpu_percent(interval=0.5)
            except Exception:
                stats["cpu_pct"] = None

            try:
                vm = psutil.virtual_memory()
                stats["ram_used"] = vm.used
                stats["ram_total"] = vm.total
                stats["ram_pct"] = vm.percent
            except Exception:
                stats["ram_used"] = stats["ram_total"] = stats["ram_pct"] = None

            try:
                disk = psutil.disk_usage("/")
                stats["disk_used"] = disk.used
                stats["disk_total"] = disk.total
                stats["disk_pct"] = disk.percent
            except Exception:
                stats["disk_used"] = stats["disk_total"] = stats["disk_pct"] = None

            try:
                stats["uptime"] = _format_uptime(
                    (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds()
                )
            except Exception:
                stats["uptime"] = "N/A"
        else:
            stats["cpu_pct"] = None
            stats["ram_used"] = stats["ram_total"] = stats["ram_pct"] = None
            stats["disk_used"] = stats["disk_total"] = stats["disk_pct"] = None
            stats["uptime"] = "N/A"

        if self.show_ip:
            stats["ip"] = _get_local_ip()

        self._stats = stats
        self._last_fetch = datetime.now()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _get_text_size(self, draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _draw_stat_card(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        label: str,
        value: str,
        *,
        warn: bool = False,
    ) -> None:
        x0, y0, x1, y1 = box
        inset = 6
        cx0, cy0, cx1, cy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset

        draw.rounded_rectangle([(cx0, cy0), (cx1, cy1)], radius=10, outline=0, width=2)

        label_font = self.fonts.get("small", self.fonts.get("default"))
        value_font = self.fonts.get("default")

        lw, lh = self._get_text_size(draw, label, label_font)
        vw, vh = self._get_text_size(draw, value, value_font)

        inner_h = cy1 - cy0
        total_text_h = lh + 6 + vh
        text_top = cy0 + max((inner_h - total_text_h) // 2, 4)

        draw.text(((cx0 + cx1 - lw) // 2, text_top), label, font=label_font, fill=0)
        val_y = text_top + lh + 6
        draw.text(((cx0 + cx1 - vw) // 2, val_y), value, font=value_font, fill=0)

        # Warn indicator: small triangle in top-right corner
        if warn:
            tx = cx1 - 10
            ty = cy0 + 5
            draw.polygon([(tx, ty + 8), (tx + 8, ty + 8), (tx + 4, ty)], fill=0)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._last_fetch is None:
            self._collect_stats()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)

        s = self._stats
        if not s:
            font = self.fonts.get("default")
            msg = "Collecting stats…"
            tw, th = self._get_text_size(draw, msg, font)
            draw.text(((width - tw) // 2, (height - th) // 2), msg, font=font, fill=0)
            return image

        padding = 16
        gap = 10

        # Build stat cards list
        cards = []

        # CPU Temp
        temp = s.get("cpu_temp")
        if temp is not None:
            temp_str = f"{temp:.1f}°C"
            warn_temp = temp >= self.temp_warn
        else:
            temp_str = "N/A"
            warn_temp = False
        cards.append(("CPU Temp", temp_str, warn_temp))

        # CPU Usage
        cpu_pct = s.get("cpu_pct")
        cards.append(("CPU Usage", f"{cpu_pct:.0f}%" if cpu_pct is not None else "N/A", False))

        # RAM
        ram_used = s.get("ram_used")
        ram_total = s.get("ram_total")
        if ram_used is not None and ram_total is not None:
            ram_str = f"{_format_bytes(ram_used)} / {_format_bytes(ram_total)}"
        else:
            ram_str = "N/A"
        cards.append(("Memory", ram_str, False))

        # Disk
        disk_used = s.get("disk_used")
        disk_total = s.get("disk_total")
        if disk_used is not None and disk_total is not None:
            disk_str = f"{_format_bytes(disk_used)} / {_format_bytes(disk_total)}"
        else:
            disk_str = "N/A"
        cards.append(("Disk (/)", disk_str, False))

        # Uptime
        cards.append(("Uptime", s.get("uptime", "N/A"), False))

        # IP
        if self.show_ip:
            cards.append(("IP Address", s.get("ip", "N/A"), False))

        # Grid layout: 3 columns × ceil(n/3) rows
        n_cols = 3
        n_rows = -(-len(cards) // n_cols)  # ceiling div
        usable_w = width - padding * 2
        usable_h = height - padding * 2
        cell_w = (usable_w - gap * (n_cols - 1)) // n_cols
        cell_h = (usable_h - gap * (n_rows - 1)) // n_rows

        for idx, (label, value, warn) in enumerate(cards):
            col = idx % n_cols
            row = idx // n_cols
            x0 = padding + col * (cell_w + gap)
            y0 = padding + row * (cell_h + gap)
            x1 = x0 + cell_w
            y1 = y0 + cell_h
            self._draw_stat_card(draw, (x0, y0, x1, y1), label, value, warn=warn)

        return image
