import importlib
import pkgutil
from pathlib import Path
from typing import Any, Dict, List, Optional


class ModuleManager:
    """Discover and run display modules."""

    def __init__(
        self,
        modules_package: str = "app.modules",
        modules_path: Optional[Path] = None,
        enabled_modules: Optional[List[str]] = None,
        module_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.modules_package = modules_package
        self.modules_path = modules_path or Path(__file__).resolve().parent.parent / "modules"
        self.enabled_modules = enabled_modules
        self.module_config = module_config or {}
        self.modules: List[Any] = []
        self._active_index = 0

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

    def _load_single_module(self, module_name: str) -> Optional[Any]:
        try:
            imported = importlib.import_module(f"{self.modules_package}.{module_name}")
        except Exception as exc:  # pragma: no cover - import-time failures logged
            print(f"[MODULES] Failed to import {module_name}: {exc}", flush=True)
            return None

        module_cls = getattr(imported, "Module", None)
        if not module_cls:
            print(f"[MODULES] {module_name} has no Module class. Skipping.", flush=True)
            return None

        cfg = self.module_config.get(module_name, {})
        instance = module_cls(config=cfg)
        print(f"[MODULES] Loaded module '{module_name}'.", flush=True)
        return instance

    def next_module(self) -> Optional[Any]:
        if not self.modules:
            return None
        module = self.modules[self._active_index]
        self._active_index = (self._active_index + 1) % len(self.modules)
        return module

    def tick_modules(self) -> None:
        for module in self.modules:
            tick = getattr(module, "tick", None)
            if callable(tick):
                tick()
