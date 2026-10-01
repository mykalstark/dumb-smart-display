"""
Shared design system for dumb-smart-display modules.

All visual constants and drawing helpers live here so every module renders
with the same spacing, radii, and header style. See docs/module-design-guide.md
for usage guidance and the new-module template.
"""
from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

from PIL import ImageDraw, ImageFont

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
PAGE_HEADER_RX = OUTER_PAD  # keep the pill clear of the display's inset frame
PAGE_HEADER_RY = 16     # vertical inset for the pill rectangle
PAGE_HEADER_RADIUS = 20 # corner radius of the pill

DIVIDER_W = 1           # thin separator / section divider line width

HEADER_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def page_body(draw: ImageDraw.ImageDraw, width: int, height: int, title: str) -> Tuple[int, int, int, int]:
    """Draw a forecast-style header and return the frame-safe body bounds."""
    header_h = min(PAGE_HEADER_H, height // 4)
    draw_page_header(draw, width, title, fit_header_font(draw, title, width, header_h), header_h)
    return OUTER_PAD, header_h + OUTER_PAD, width - OUTER_PAD, height - OUTER_PAD


def fit_font(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int, height: int, min_size: int = 12) -> Any:
    """Shrink a scalable font to fit visible glyphs, preserving its family."""
    font = font or ImageFont.load_default()
    start = int(getattr(font, "size", min_size))
    for size in range(start, min(start, min_size) - 1, -1):
        try:
            candidate = font.font_variant(size=size)
        except (AttributeError, OSError):
            candidate = font
        tw, th = get_text_size(draw, text, candidate)
        if tw <= width and th <= height:
            return candidate
    return candidate


def ellipsize(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> str:
    """Fit one line, including its ellipsis, using actual pixel measurements."""
    text = " ".join(str(text).split())
    if get_text_size(draw, text, font)[0] <= width:
        return text
    if get_text_size(draw, "…", font)[0] > width:
        return ""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if get_text_size(draw, text[:mid] + "…", font)[0] <= width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + "…"


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> list[str]:
    """Wrap by measured pixels, splitting long words when necessary."""
    lines, line = [], ""
    for word in str(text).split():
        candidate = (line + " " + word).strip()
        if get_text_size(draw, candidate, font)[0] <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        if get_text_size(draw, word, font)[0] <= width:
            line = word
            continue
        for char in word:
            if line and get_text_size(draw, line + char, font)[0] > width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def draw_text_block(
    draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], text: str, font: Any,
    fill: int = 0, *, max_lines: int = 1, align: str = "center", min_size: int = 12,
) -> None:
    """Fit, wrap and centre visible text inside a box; ellipsize overflow."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0 or not text:
        return
    text = " ".join(str(text).split())
    if not text:
        return
    font = font or ImageFont.load_default()
    start = int(getattr(font, "size", min_size))
    for size in range(start, min(start, min_size) - 1, -1):
        try:
            candidate = font.font_variant(size=size)
        except (AttributeError, OSError):
            candidate = font
        lines = wrap_text(draw, text, candidate, width) if max_lines > 1 else [text]
        line_h = max(get_text_size(draw, line or "Ag", candidate)[1] for line in lines)
        if (len(lines) <= max_lines and max(get_text_size(draw, line, candidate)[0] for line in lines) <= width
                and len(lines) * line_h + (len(lines) - 1) * LINE_SPACING <= height):
            break
    capacity = min(max_lines, max(0, (height + LINE_SPACING) // (line_h + LINE_SPACING)))
    if not capacity:
        return
    if len(lines) > capacity:
        lines = lines[:capacity - 1] + [" ".join(lines[capacity - 1:])]
    lines = [ellipsize(draw, line, candidate, width) for line in lines]
    block_h = len(lines) * line_h + (len(lines) - 1) * LINE_SPACING
    y = y0 + (height - block_h) // 2
    for line in lines:
        if align == "left":
            left, top, _, _ = draw.textbbox((0, 0), line, font=candidate)
            draw.text((x0 - left, y - top), line, font=candidate, fill=fill)
        else:
            draw_centered_text(draw, (x0, y, x1, y + line_h), line, candidate, fill)
        y += line_h + LINE_SPACING


def draw_message(draw: ImageDraw.ImageDraw, width: int, height: int, text: str, font: Any) -> None:
    draw_text_block(draw, (OUTER_PAD, OUTER_PAD, width - OUTER_PAD, height - OUTER_PAD),
                    text, font, max_lines=4)


def draw_list(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], items: Sequence[str],
              font: Any, small_font: Any, *, overflow: int = 0, empty: str = "No items",
              max_lines: int = 2) -> None:
    """Fit complete list rows and report all items hidden by the available height."""
    x0, y0, x1, y1 = box
    if not items:
        draw_text_block(draw, (x0, y0, x1, min(y1, y0 + 32)), empty, font, align="left")
        return
    line_h = get_text_size(draw, "Ag", font)[1]
    footer_h = get_text_size(draw, "+999 more…", small_font)[1] + LINE_SPACING
    rows = []
    for text in items:
        lines = wrap_text(draw, text, font, x1 - x0) or [""]
        count = min(max_lines, len(lines))
        if len(lines) > count:
            lines = lines[:count - 1] + [" ".join(lines[count - 1:])]
        lines = [ellipsize(draw, line, font, x1 - x0) for line in lines]
        rows.append((lines, count * line_h + (count - 1) * LINE_SPACING))
    needs_footer = overflow > 0 or sum(h + LINE_SPACING for _, h in rows) - LINE_SPACING > y1 - y0
    bottom = y1 - footer_h - LINE_SPACING if needs_footer else y1
    shown = 0
    for lines, row_h in rows:
        if y0 + row_h > bottom:
            break
        for line in lines:
            draw_text_block(draw, (x0, y0, x1, y0 + line_h), line, font, align="left")
            y0 += line_h + LINE_SPACING
        shown += 1
    hidden = len(items) - shown + overflow
    if hidden:
        draw_text_block(draw, (x0, y1 - footer_h, x1, y1), f"+{hidden} more…", small_font, align="left")


def draw_metrics(
    draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
    labels: Sequence[str], values: Sequence[str], label_font: Any, value_font: Any, fill: int = 0,
) -> None:
    """Place metrics in columns, or stack them in narrow sidebar cards."""
    x0, y0, x1, y1 = box
    vertical = x1 - x0 < 240
    count = len(labels)
    for i, (label, value) in enumerate(zip(labels, values)):
        if vertical:
            a, b = y0 + i * (y1 - y0) // count, y0 + (i + 1) * (y1 - y0) // count
            cell = (x0, a, x1, b)
        else:
            a, b = x0 + i * (x1 - x0) // count, x0 + (i + 1) * (x1 - x0) // count
            cell = (a, y0, b, y1)
        cx0, cy0, cx1, cy1 = cell
        inset = min(INNER_PAD, max(2, (cy1 - cy0) // 12))
        mid = cy0 + (cy1 - cy0) * 2 // 5
        draw_text_block(draw, (cx0 + inset, cy0 + inset, cx1 - inset, mid), label, label_font, fill)
        draw_text_block(draw, (cx0 + inset, mid + 2, cx1 - inset, cy1 - inset), value, value_font, fill)
        if i:
            if vertical:
                draw.line([(cx0 + INNER_PAD, cy0), (cx1 - INNER_PAD, cy0)], fill=fill, width=DIVIDER_W)
            else:
                draw.line([(cx0, cy0 + INNER_PAD), (cx0, cy1 - INNER_PAD)], fill=fill, width=DIVIDER_W)


def layout_slots(layout: Any, width: int, height: int) -> Dict[str, Tuple[int, int, int, int]]:
    """Lay out preset cards with consistent gaps and clearance from the frame."""
    occupied = [[False] * layout.columns for _ in range(layout.rows)]
    slots = {}
    cw = (width - 2 * OUTER_PAD + COL_GAP) / layout.columns
    ch = (height - 2 * OUTER_PAD + COL_GAP) / layout.rows
    for slot in layout.slots:
        placed = False
        for row in range(layout.rows - slot.rowspan + 1):
            for col in range(layout.columns - slot.colspan + 1):
                if any(occupied[r][c] for r in range(row, row + slot.rowspan) for c in range(col, col + slot.colspan)):
                    continue
                for r in range(row, row + slot.rowspan):
                    for c in range(col, col + slot.colspan):
                        occupied[r][c] = True
                slots[slot.key] = (OUTER_PAD + round(col * cw), OUTER_PAD + round(row * ch),
                                   OUTER_PAD + round((col + slot.colspan) * cw) - COL_GAP,
                                   OUTER_PAD + round((row + slot.rowspan) * ch) - COL_GAP)
                placed = True
                break
            if placed:
                break
    return slots


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


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: Any,
    fill: int = 0,
) -> None:
    """Centre the visible glyph bounds, including the font's bearing offsets."""
    x0, y0, x1, y1 = box
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (x0 + (x1 - x0 - (right - left)) // 2 - left,
         y0 + (y1 - y0 - (bottom - top)) // 2 - top),
        text, font=font, fill=fill,
    )


def fit_header_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    width: int,
    header_h: int = PAGE_HEADER_H,
    min_size: int = 16,
) -> Any:
    """Return the largest DejaVuSans-Bold font whose rendered *text* fits the pill interior.

    Tries sizes from 80 px down to *min_size*, returning the first that fits within
    the usable area (pill interior minus safety margins). Falls back to a small size
    or the default bitmap font if the bold TTF cannot be loaded.
    """
    max_w = width - 2 * PAGE_HEADER_RX - 16   # 16 px total horizontal safety padding
    max_h = header_h - 2 * PAGE_HEADER_RY - 4  # 4 px total vertical safety padding
    for size in range(80, min_size - 1, -1):
        try:
            font = ImageFont.truetype(HEADER_FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()
        tw, th = get_text_size(draw, text, font)
        if tw <= max_w and th <= max_h:
            return font
    try:
        return ImageFont.truetype(HEADER_FONT_PATH, min_size)
    except Exception:
        return ImageFont.load_default()


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
        [(PAGE_HEADER_RX, PAGE_HEADER_RY), (width - PAGE_HEADER_RX - 1, header_h - PAGE_HEADER_RY)],
        radius=PAGE_HEADER_RADIUS,
        fill=0,
    )
    # White centred text inside the pill
    draw_text_block(
        draw,
        (PAGE_HEADER_RX + 8, PAGE_HEADER_RY, width - PAGE_HEADER_RX - 8, header_h - PAGE_HEADER_RY),
        text, font, fill=255,
    )
    # 1px divider below the header zone
    draw.line([(OUTER_PAD, header_h), (width - OUTER_PAD - 1, header_h)], fill=0, width=DIVIDER_W)


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
    draw.rounded_rectangle([(x0, y0), (x1 - 1, y1 - 1)], radius=radius, outline=0, width=outline)


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
    font = fit_font(draw, text, font, x1 - x0 - 2 * inner_pad, 48)
    text = ellipsize(draw, text, font, x1 - x0 - 2 * inner_pad)
    tw, th = get_text_size(draw, text, font)
    left, top, _, _ = draw.textbbox((0, 0), text, font=font)
    draw.text((x0 + inner_pad - left, y0 + inner_pad - top), text, font=font, fill=0)
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
