"""Bob Labs — dynamic Open Graph image renderer for blog posts.

Renders 1200x630 PNGs server-side with PIL. No headless browser dependency.
Uses DejaVu Sans (bundled in fonts-dejavu — already pulled by the Dockerfile
font deps line via fonts-liberation; DejaVu is installed by default on Debian
slim too).

LRU-cached by (slug, updated_at_epoch) so repeated bot fetches don't re-render.
"""

from __future__ import annotations

import functools
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Layout constants ────────────────────────────
WIDTH = 1200
HEIGHT = 630
PADDING = 72

BG_TOP = (15, 18, 30)  # near-black
BG_BOTTOM = (28, 32, 56)  # subtle dark-blue gradient
ACCENT = (122, 162, 247)  # Bob Labs accent (cool blue)
FG_TITLE = (245, 247, 252)
FG_SUMMARY = (180, 188, 204)
FG_FOOTER = (140, 148, 168)

TITLE_MAX_LINES = 4
SUMMARY_MAX_LINES = 3

# ── Font resolution ─────────────────────────────
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = _FONT_CANDIDATES if bold else _FONT_REGULAR_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:  # pragma: no cover
                continue
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int) -> list[str]:
    """Greedy word-wrap. Returns up to max_lines lines, eliding the last with '…'."""
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) >= max_lines and (cur or len(words) > sum(len(l.split()) for l in lines)):
        # Truncate last line with ellipsis
        last = lines[-1]
        while font.getlength(last + "…") > max_w and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last + "…"
    return lines


def _gradient_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


@functools.lru_cache(maxsize=256)
def _render_cached(title: str, summary: str, identity: str) -> bytes:
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    _gradient_background(draw)

    # Accent stripe top-left
    draw.rectangle([(0, 0), (12, HEIGHT)], fill=ACCENT)

    # Brand mark, top
    brand_font = _font(28, bold=True)
    draw.text((PADDING, PADDING - 24), "◆ Bob Labs", font=brand_font, fill=ACCENT)

    # Title — auto-shrink for very long titles
    title_size = 64
    title_font = _font(title_size, bold=True)
    title_lines = _wrap(title, title_font, WIDTH - 2 * PADDING, TITLE_MAX_LINES)
    while len(title_lines) >= TITLE_MAX_LINES and title_size > 40:
        title_size -= 6
        title_font = _font(title_size, bold=True)
        title_lines = _wrap(title, title_font, WIDTH - 2 * PADDING, TITLE_MAX_LINES)

    y = PADDING + 56
    for line in title_lines:
        draw.text((PADDING, y), line, font=title_font, fill=FG_TITLE)
        y += int(title_size * 1.2)

    # Summary
    if summary:
        summary_font = _font(28)
        sum_lines = _wrap(summary, summary_font, WIDTH - 2 * PADDING, SUMMARY_MAX_LINES)
        y += 24
        for line in sum_lines:
            draw.text((PADDING, y), line, font=summary_font, fill=FG_SUMMARY)
            y += 36

    # Footer — identity badge + URL
    footer_font = _font(24, bold=True)
    badge_text = f"{'🤖' if identity.lower().startswith('agent') else '👤'} {identity}"
    draw.text(
        (PADDING, HEIGHT - PADDING - 28),
        badge_text,
        font=footer_font,
        fill=FG_FOOTER,
    )
    url_font = _font(22)
    url_text = "lab.boblabs.eu/blog"
    url_w = url_font.getlength(url_text)
    draw.text(
        (WIDTH - PADDING - url_w, HEIGHT - PADDING - 26),
        url_text,
        font=url_font,
        fill=FG_FOOTER,
    )

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_og_png(
    *,
    title: str,
    summary: str,
    identity: str,
    cache_key: tuple,  # noqa: ARG001  (kept in signature so caller communicates versioning intent)
) -> bytes:
    """Render a 1200x630 PNG OG card. Result cached in-process by content."""
    return _render_cached(title or "", summary or "", identity or "")
