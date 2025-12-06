"""Module discovery and lifecycle management."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.module_interface import DisplayModule


class ModuleManager:
    """Discover, load, and coordinate display modules."""

    def __init__(
        self,
        fonts: Dict[str, Any],
        modules_package: str = "app.modules",
        modules_path: Optional[Path] = None,
        enabled_modules: Optional[List[str]] = None,
        module_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.fonts = fonts
        self.modules_package = modules_package
        self.modules_path = modules_path or Path(__file__).resolve().parent.parent / "modules"
        self.enabled_modules = enabled_modules
        self.module_config = module_config or {}
        self.modules: List[DisplayModule] = []
        self._active_index: Optional[int] = None

    # ------------------------------------------------------------------
    # Module discovery & loading
    # ------------------------------------------------------------------
    def discover_available_modules(self) -> List[str]:
        """Return all module names available in app.modules."""
        names: List[str] = []
        if not self.modules_path.exists():
            return names

        for module_info in pkgutil.iter_modules([str(self.modules_path)]):
            if module_info.name.startswith("__"):
                continue
            names.append(module_info.name)
        return names

    def load_modules(self) -> None:
        """Import and instantiate configured modules."""
        to_load = self.enabled_modules or self.discover_available_modules()
        for name in to_load:
            module_instance = self._load_single_module(name)
            if module_instance:
                self.modules.append(module_instance)

        if self.modules:
            self._active_index = 0

    def _load_single_module(self, module_name: str) -> Optional[DisplayModule]:
        try:
            imported = importlib.import_module(f"{self.modules_package}.{module_name}")
        except Exception as exc:
            print(f"[MODULES] Failed to import {module_name}: {exc}", flush=True)
            return None

        module_cls = getattr(imported, "Module", None)
        if module_cls is None:
            print(f"[MODULES] {module_name} has no Module class. Skipping.", flush=True)
            return None

        cfg = self.module_config.get(module_name, {})

        try:
            instance: DisplayModule = module_cls(config=cfg, fonts=self.fonts)
        except TypeError:
            instance = module_cls(config=cfg)  # type: ignore[call-arg]

        print(f"[MODULES] Loaded module '{module_name}'.", flush=True)
        return instance

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def _has_modules(self) -> bool:
        return bool(self.modules)

    def current_module(self) -> Optional[DisplayModule]:
        if not self._has_modules():
            return None
        if self._active_index is None:
            self._active_index = 0
        return self.modules[self._active_index]

    def next_module(self) -> Optional[DisplayModule]:
        if not self._has_modules():
            return None
        if self._active_index is None:
            self._active_index = 0
        module = self.modules[self._active_index]
        self._active_index = (self._active_index + 1) % len(self.modules)
        return module

    def prev_module(self) -> Optional[DisplayModule]:
        if not self._has_modules():
            return None
        if self._active_index is None:
            self._active_index = 0
        self._active_index = (self._active_index - 1) % len(self.modules)
        return self.modules[self._active_index]

    def activate_next(self) -> Optional[DisplayModule]:
        """Advance to and return the next module in sequence."""
        if not self._has_modules():
            return None
        if self._active_index is None:
            self._active_index = 0
        self._active_index = (self._active_index + 1) % len(self.modules)
        return self.current_module()

    # ------------------------------------------------------------------
    # Button routing & background work
    # ------------------------------------------------------------------
    def refresh_current(self) -> Optional[DisplayModule]:
        """Force the active module to refresh its data if possible."""

        module = self.current_module()
        if module is None:
            return None

        refresher = getattr(module, "force_refresh", None)
        if callable(refresher):
            refresher()
        else:
            module.tick()

        return module

    def route_button_event(self, event: str) -> Optional[DisplayModule]:
        """Handle a logical button event (back/refresh/next)."""
        if event == "next":
            return self.activate_next()
        if event in {"prev", "back"}:
            return self.prev_module()
        if event == "refresh":
            return self.refresh_current()
        if event == "action":
            module = self.current_module()
            if module and hasattr(module, "handle_button"):
                module.handle_button(event)
            return module
        return self.current_module()

    def tick_modules(self) -> None:
        for module in self.modules:
            module.tick()
