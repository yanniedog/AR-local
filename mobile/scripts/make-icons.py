"""Generate the app icon / adaptive icon / splash / favicon for AR Rates.

Pure-PIL, deterministic. Run from anywhere:

    python mobile/scripts/make-icons.py

Writes PNGs into mobile/assets/. Mark matches dashboard `site/assets/branding/ar-mark.svg`.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"

# Pi dashboard dark shell (`site/foundation.css` :root[data-theme="dark"])
BG = (11, 14, 17, 255)  # #0b0e11
MARK_BG = (7, 17, 31, 255)  # #07111f
MARK_TILE = (34, 211, 238, 61)  # cyan gradient wash at ~24% on tile
ROOF = (226, 248, 255, 255)  # #e2f8ff
CHART = (125, 211, 252, 255)  # #7dd3fc


def _ar_mark(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """Simplified raster of `ar-mark.svg` (house roof + rising rate chart)."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    radius = int(w * 0.23)
    draw.rounded_rectangle(box, radius=radius, fill=MARK_BG)
    inner = (
        x0 + w * 0.02,
        y0 + h * 0.02,
        x1 - w * 0.02,
        y1 - h * 0.02,
    )
    draw.rounded_rectangle(inner, radius=int(radius * 0.9), fill=MARK_TILE)

    cx = (x0 + x1) / 2
    roof_y = y0 + h * 0.42
    left_x = x0 + w * 0.10
    right_x = x1 - w * 0.10
    peak_y = y0 + h * 0.17
    draw.line([(left_x, roof_y), (cx, peak_y), (right_x, roof_y)], fill=ROOF, width=max(2, int(w * 0.07)))

    base_y = y0 + h * 0.71
    draw.line([(x0 + w * 0.19, base_y), (x1 - w * 0.19, base_y)], fill=ROOF, width=max(2, int(w * 0.06)))

    chart = [
        (x0 + w * 0.24, y0 + h * 0.58),
        (x0 + w * 0.35, y0 + h * 0.46),
        (x0 + w * 0.46, y0 + h * 0.52),
        (x0 + w * 0.62, y0 + h * 0.36),
    ]
    draw.line(chart, fill=CHART, width=max(2, int(w * 0.06)), joint="curve")
    dot_r = max(2, int(w * 0.05))
    dot_x = x0 + w * 0.66
    dot_y = y0 + h * 0.40
    draw.ellipse((dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r), fill=CHART)


def make_icon() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), BG)
    inset = int(size * 0.14)
    _ar_mark(ImageDraw.Draw(img), (inset, inset, size - inset, size - inset))
    img.save(ASSETS / "icon.png")
    img.resize((64, 64)).save(ASSETS / "favicon.png")


def make_adaptive() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = int(size * 0.2)
    _ar_mark(ImageDraw.Draw(img), (margin, margin, size - margin, size - margin))
    img.save(ASSETS / "adaptive-icon.png")


def make_splash() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = int(size * 0.28)
    _ar_mark(ImageDraw.Draw(img), (margin, margin, size - margin, size - margin))
    img.save(ASSETS / "splash.png")


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_icon()
    make_adaptive()
    make_splash()
    print(f"Wrote icons to {ASSETS}")
