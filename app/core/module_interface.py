"""Shared interface definition for display modules.

Modules should expose a ``Module`` class that implements the
``DisplayModule`` protocol below. The protocol describes the lifecycle hooks
used by the ``ModuleManager`` as well as optional hooks for layout metadata.

Required hooks
==============

- ``name`` (str): human-readable name for logging/navigation.
- ``render(width, height, **kwargs)`` -> ``PIL.Image.Image``: generate the
  frame for the current cycle.
- ``tick()`` -> ``None``: periodic background work that runs even when the
  module is not active (e.g., refreshing cached data).
- ``handle_button(event)`` -> ``None``: react to logical button events such as
  ``"prev"``, ``"next"``, or ``"action"``.

Optional hooks
==============

- ``refresh_interval()`` -> ``Optional[int]``: provide a hint (in seconds) for
  how frequently the module should be refreshed. Returning ``None`` disables
  the hint.
- ``supported_layouts()`` -> ``Sequence[LayoutPreset]``: describe layout
  variants the module can render, using the presets defined below. If the
  method is omitted, consumers should assume only the ``"full"`` layout is
  supported.

Layout presets
==============

Layouts are described as lightweight presets that communicate how many slots a
module can render and whether a preset is a compact option. Each preset uses a
simple grid made up of ``columns`` and ``rows`` counts. ``LayoutSlot`` entries
describe the position of one logical section by defining how many columns and
rows it spans. The presets map to the sample layouts shown in the reference
image used during planning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

from PIL import Image


@dataclass(frozen=True)
class LayoutSlot:
    """A logical slot inside a layout grid.

    ``colspan`` and ``rowspan`` are relative spans inside the preset grid. A
    slot covering the entire layout would use the same values as the preset's
    column and row count.
    """

    key: str
    colspan: int = 1
    rowspan: int = 1


@dataclass(frozen=True)
class LayoutPreset:
    """Declarative layout option a module can implement.

    The ``compact`` flag helps UIs choose denser presets when space is limited
    (for example, smaller e-paper panels). ``slots`` are ordered to help
    consumers assign content deterministically.
    """

    name: str
    columns: int
    rows: int
    slots: Tuple[LayoutSlot, ...]
    description: str
    compact: bool = False


# Layout presets matching the visual examples in the design reference.
DEFAULT_LAYOUTS: Tuple[LayoutPreset, ...] = (
    LayoutPreset(
        name="full",
        columns=4,
        rows=2,
        slots=(LayoutSlot("main", colspan=4, rowspan=2),),
        description="Single canvas taking the full display area.",
    ),
    LayoutPreset(
        name="wide_left",
        columns=4,
        rows=2,
        slots=(
            LayoutSlot("primary", colspan=3, rowspan=2),
            LayoutSlot("secondary", colspan=1, rowspan=2),
        ),
        description="Large area on the left with a tall sidebar on the right.",
    ),
    LayoutPreset(
        name="wide_right",
        columns=4,
        rows=2,
        slots=(
            LayoutSlot("primary", colspan=3, rowspan=2),
            LayoutSlot("secondary", colspan=1, rowspan=1),
            LayoutSlot("tertiary", colspan=1, rowspan=1),
        ),
        description="Large area on the right with two stacked panels on the left.",
    ),
    LayoutPreset(
        name="three_column",
        columns=3,
        rows=2,
        slots=(
            LayoutSlot("a", colspan=1, rowspan=2),
            LayoutSlot("b", colspan=1, rowspan=1),
            LayoutSlot("c", colspan=1, rowspan=1),
            LayoutSlot("d", colspan=1, rowspan=1),
            LayoutSlot("e", colspan=1, rowspan=1),
        ),
        description="Three columns with mixed tall and short cards.",
    ),
    LayoutPreset(
        name="quads",
        columns=2,
        rows=2,
        slots=(
            LayoutSlot("top_left"),
            LayoutSlot("top_right"),
            LayoutSlot("bottom_left"),
            LayoutSlot("bottom_right"),
        ),
        description="Four even quadrants for equally weighted content.",
    ),
    LayoutPreset(
        name="compact_quads",
        columns=2,
        rows=3,
        slots=(
            LayoutSlot("main", colspan=2, rowspan=1),
            LayoutSlot("bottom_left"),
            LayoutSlot("bottom_right"),
            LayoutSlot("footer_left"),
            LayoutSlot("footer_right"),
        ),
        description="Narrow header with stacked compact cards beneath.",
        compact=True,
    ),
    LayoutPreset(
        name="striped_rows",
        columns=3,
        rows=2,
        slots=(
            LayoutSlot("row1_left", colspan=2, rowspan=1),
            LayoutSlot("row1_right", colspan=1, rowspan=1),
            LayoutSlot("row2_left", colspan=1, rowspan=1),
            LayoutSlot("row2_center", colspan=1, rowspan=1),
            LayoutSlot("row2_right", colspan=1, rowspan=1),
        ),
        description="Mixed stripes with a wide header row and smaller tiles below.",
        compact=True,
    ),
)


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

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        ...


class BaseDisplayModule:
    """Convenience base class that supplies optional hooks.

    Modules can inherit from this class to avoid re-implementing optional
    behaviors such as refresh cadence or layout metadata.
    """

    name: str = "unnamed"

    def refresh_interval(self) -> Optional[int]:  # pragma: no cover - trivial
        return None

    def supported_layouts(self) -> Sequence[LayoutPreset]:  # pragma: no cover - trivial
        return (DEFAULT_LAYOUTS[0],)
