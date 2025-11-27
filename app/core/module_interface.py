"""Shared interface definition for display modules.

Modules should expose a ``Module`` class that implements this protocol:

- ``name`` (str): human-readable name for logging/navigation
- ``render(width, height, **kwargs)`` -> ``PIL.Image.Image``: generate the frame
- ``tick()`` -> ``None``: periodic background work
- ``handle_button(event)`` -> ``None``: react to a logical button event
- ``refresh_interval()`` -> ``Optional[int]``: optional refresh cadence hint

These methods provide a common contract for the ``ModuleManager`` and
button-handling code. Existing modules can opt out of the refresh hint by
returning ``None``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class DisplayModule(Protocol):
    name: str

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        ...

    def render(self, width: int, height: int, **kwargs: Any) -> Image.Image:
        ...

    def tick(self) -> None:
        ...

    def handle_button(self, event: str) -> None:
        ...

    def refresh_interval(self) -> Optional[int]:
        ...
