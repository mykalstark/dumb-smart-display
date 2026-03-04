# Module Design Guide

Visual standards for dumb-smart-display modules. All constants and helpers
are in `app/core/theme.py` — import from there instead of hardcoding values.

---

## Quick start

```python
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, LINE_SPACING,
    CARD_RADIUS, CARD_OUTLINE,
    PAGE_HEADER_H, PAGE_HEADER_FONT_SIZE,
    draw_page_header, draw_card, draw_card_header, draw_divider, get_text_size,
)
```

---

## Design constants

| Constant | Value | Use |
|---|---|---|
| `OUTER_PAD` | 20 px | Gap from display edge to card/content edge |
| `INNER_PAD` | 12 px | Padding inside cards (header text, body margin) |
| `COL_GAP` | 12 px | Gap between adjacent columns or cards |
| `LINE_SPACING` | 6 px | Vertical gap between wrapped text lines |
| `CARD_RADIUS` | 16 px | `rounded_rectangle` corner radius for all cards |
| `CARD_OUTLINE` | 2 px | Card border stroke width |
| `PAGE_HEADER_H` | 112 px | Height of the top header zone |
| `PAGE_HEADER_FONT_SIZE` | 36 px | Font size for page header text |
| `DIVIDER_W` | 1 px | Thin separator / section divider line width |

---

## Color scheme

The display is 1-bit black and white. All images are created as:

```python
image = Image.new("1", (width, height), 255)  # white background
```

| Value | Meaning |
|---|---|
| `255` | White — background, text on dark fill |
| `0` | Black — text, borders, filled shapes |

Never use intermediate greys — they dither and look noisy on e-ink.

---

## Font keys (loaded by `main.py`)

| Key | Size | Weight | Use |
|---|---|---|---|
| `"small"` | 18 px | Regular | Timestamps, labels, footnotes |
| `"default"` | 24 px | Regular | Body text, page header text |
| `"large"` | 48 px | Bold | Card section headers, primary data |

Access via `self.fonts.get("default")`. Always provide a fallback:
`self.fonts.get("large", self.fonts.get("default"))`.

For bigger sizes (times, big numbers), load directly:

```python
from PIL import ImageFont
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
```

---

## Text size (Pillow 10+)

Use the theme helper — do not copy the `textbbox` pattern manually:

```python
from app.core.theme import get_text_size
w, h = get_text_size(draw, "Hello", font)
```

---

## Helper functions

### `draw_page_header(draw, width, text, font, header_h=PAGE_HEADER_H)`

Draws the standard full-width black pill header and a 1 px divider line below.
Call this first in `render()`. Body content starts at `PAGE_HEADER_H + 1`.

```python
draw_page_header(draw, width, "My Screen", self.fonts.get("default"))
body_top = PAGE_HEADER_H + OUTER_PAD
```

### `draw_card(draw, x0, y0, x1, y1, radius=CARD_RADIUS, outline=CARD_OUTLINE)`

Draws a rounded-rectangle card border (no fill).

```python
draw_card(draw, x0, y0, x1, y1)
```

### `draw_card_header(draw, x0, y0, x1, text, font, inner_pad=INNER_PAD) -> int`

Draws a left-aligned section heading inside a card with a 1 px divider below.
Returns the y coordinate just below the divider so you can start body content there.

```python
content_y = draw_card_header(draw, x0, y0, x1, "Today", header_font)
# start drawing content at content_y + INNER_PAD
```

### `draw_divider(draw, x0, x1, y, width=DIVIDER_W)`

Draws a horizontal 1 px separator line. Use for in-body section breaks.

---

## Common layout patterns

### Full-screen with page header

```
┌─────────────────────────────────────┐  ← y=0
│  ╔═══════════════════════════════╗  │
│  ║        Page Title             ║  │  ← PAGE_HEADER_H (56px)
│  ╚═══════════════════════════════╝  │
├─────────────────────────────────────┤  ← divider
│                                     │
│           body content              │  ← starts at PAGE_HEADER_H + OUTER_PAD
│                                     │
└─────────────────────────────────────┘  ← y=height
```

### Two-column card layout

```python
padding = OUTER_PAD       # 20
gap     = COL_GAP         # 12
col_w   = (width - padding * 2 - gap) // 2

left_box  = (padding,           padding, padding + col_w,       height - padding)
right_box = (padding + col_w + gap, padding, width - padding,   height - padding)

draw_card(draw, *left_box)
draw_card(draw, *right_box)
```

### Grid of stat cards

```python
n_cols = 3
n_rows = -(-len(cards) // n_cols)          # ceiling div
usable_w = width  - OUTER_PAD * 2
usable_h = height - OUTER_PAD * 2
cell_w = (usable_w - COL_GAP * (n_cols - 1)) // n_cols
cell_h = (usable_h - COL_GAP * (n_rows - 1)) // n_rows

for idx, card_data in enumerate(cards):
    col = idx % n_cols
    row = idx // n_cols
    x0 = OUTER_PAD + col * (cell_w + COL_GAP)
    y0 = OUTER_PAD + row * (cell_h + COL_GAP)
    draw_card(draw, x0, y0, x0 + cell_w, y0 + cell_h)
```

---

## New module template

```python
"""One-line description of what this module shows."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

from PIL import Image, ImageDraw

from app.core.module_interface import BaseDisplayModule, DEFAULT_LAYOUTS, LayoutPreset
from app.core.theme import (
    OUTER_PAD, INNER_PAD, COL_GAP, LINE_SPACING,
    PAGE_HEADER_H,
    draw_page_header, draw_card, get_text_size,
)

log = logging.getLogger(__name__)


class Module(BaseDisplayModule):
    name = "my_module"          # must match the key in config.yml

    def __init__(self, config: Dict[str, Any], fonts: Dict[str, Any]) -> None:
        self.config = config or {}
        self.fonts = fonts
        # … read config keys …
        self._data = None
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def refresh_interval(self) -> Optional[int]:
        return 300  # seconds between auto-refresh (None = never)

    def tick(self) -> None:
        self._fetch()

    def handle_button(self, event: str) -> None:
        pass  # handle "next" / "prev" / "refresh" if needed

    def supported_layouts(self) -> Sequence[LayoutPreset]:
        return (DEFAULT_LAYOUTS[0],)  # "full" layout

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _fetch(self) -> None:
        try:
            pass  # fetch data, set self._data
            self._error = None
        except Exception as exc:
            log.warning("my_module: fetch failed: %s", exc)
            self._error = "Data unavailable"

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, width: int = 800, height: int = 480, **kwargs: Any) -> Image.Image:
        if self._data is None:
            self._fetch()

        image = Image.new("1", (width, height), 255)
        draw = ImageDraw.Draw(image)
        default_font = self.fonts.get("default")

        # Error state
        if self._error or self._data is None:
            msg = self._error or "No data"
            tw, th = get_text_size(draw, msg, default_font)
            draw.text(((width - tw) // 2, (height - th) // 2), msg, font=default_font, fill=0)
            return image

        # Page header
        draw_page_header(draw, width, "My Screen", default_font)
        body_top = PAGE_HEADER_H + OUTER_PAD

        # … draw body content below body_top …

        return image
```

---

## Checklist for new modules

- [ ] Import from `app.core.theme` — no inline magic numbers for spacing or radius
- [ ] Start `render()` with `Image.new("1", (width, height), 255)`
- [ ] Handle the error / no-data state before drawing anything else
- [ ] Call `draw_page_header()` if the module occupies the full screen
- [ ] Use `draw_card()` for any bordered panels instead of `draw.rectangle()`
- [ ] Use `get_text_size()` from theme instead of a local `textbbox` wrapper
- [ ] Outer padding = `OUTER_PAD` (20 px), inner = `INNER_PAD` (12 px)
- [ ] Card corner radius = `CARD_RADIUS` (16 px)
- [ ] Text on a black fill = `fill=255`; text on white = `fill=0`
