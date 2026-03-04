"""
Shared design system for dumb-smart-display modules.

All visual constants and drawing helpers live here so every module renders
with the same spacing, radii, and header style. See docs/module-design-guide.md
for usage guidance and the new-module template.
"""
from __future__ import annotations

from typing import Any, Tuple

from PIL import ImageDraw

# ---------------------------------------------------------------------------
# Design constants
# ---------------------------------------------------------------------------

OUTER_PAD = 20          # screen edge → content / card edge
INNER_PAD = 12          # padding inside cards and column headers
COL_GAP = 12            # gap between adjacent columns / cards
LINE_SPACING = 6        # vertical gap between wrapped text lines

CARD_RADIUS = 16        # rounded_rectangle corner radius for all cards
CARD_OUTLINE = 2        # card border stroke width

PAGE_HEADER_H = 112     # height of the top header zone (px)
PAGE_HEADER_RX = 16     # horizontal inset for the pill rectangle
PAGE_HEADER_RY = 16     # vertical inset for the pill rectangle
PAGE_HEADER_RADIUS = 20 # corner radius of the pill
PAGE_HEADER_FONT_SIZE = 36  # font size for page header text

DIVIDER_W = 1           # thin separator / section divider line width


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_text_size(draw: ImageDraw.ImageDraw, text: str, font: Any) -> Tuple[int, int]:
    """Return (width, height) of *text* rendered in *font*.

    Uses the Pillow 10+ ``textbbox`` API so modules don't need their own
    copy-paste of this pattern.
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_page_header(
    draw: ImageDraw.ImageDraw,
    width: int,
    text: str,
    font: Any,
    header_h: int = PAGE_HEADER_H,
) -> None:
    """Draw the standard black pill page header and a 1px bottom divider.

    Call this at the very start of ``render()`` before drawing body content.
    The body should start at ``header_h + 1``.
    """
    # Black rounded rectangle (the pill)
    draw.rounded_rectangle(
        [(PAGE_HEADER_RX, PAGE_HEADER_RY), (width - PAGE_HEADER_RX, header_h - PAGE_HEADER_RY)],
        radius=PAGE_HEADER_RADIUS,
        fill=0,
    )
    # White centred text inside the pill
    tw, th = get_text_size(draw, text, font)
    rect_inner_h = header_h - 2 * PAGE_HEADER_RY
    draw.text(
        ((width - tw) // 2, PAGE_HEADER_RY + (rect_inner_h - th) // 2),
        text,
        font=font,
        fill=255,
    )
    # 1px divider below the header zone
    draw.line([(0, header_h), (width, header_h)], fill=0, width=1)


def draw_card(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    radius: int = CARD_RADIUS,
    outline: int = CARD_OUTLINE,
) -> None:
    """Draw a rounded rectangle card outline (no fill)."""
    draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=radius, outline=0, width=outline)


def draw_card_header(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    text: str,
    font: Any,
    inner_pad: int = INNER_PAD,
) -> int:
    """Draw a left-aligned section header inside a card with a 1px divider below.

    Returns the y coordinate immediately below the divider line — the caller
    should start body content there (plus any desired gap).
    """
    tw, th = get_text_size(draw, text, font)
    draw.text((x0 + inner_pad, y0 + inner_pad), text, font=font, fill=0)
    sep_y = y0 + inner_pad + th + inner_pad // 2
    draw.line([(x0 + inner_pad, sep_y), (x1 - inner_pad, sep_y)], fill=0, width=DIVIDER_W)
    return sep_y + DIVIDER_W


def draw_divider(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    width: int = DIVIDER_W,
) -> None:
    """Draw a horizontal divider line from *x0* to *x1* at height *y*."""
    draw.line([(x0, y), (x1, y)], fill=0, width=width)
