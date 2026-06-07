"""Generate the app icon / adaptive icon / splash / favicon for AR Rates.

Pure-PIL, deterministic. Run from anywhere:

    python mobile/scripts/make-icons.py

Writes PNGs into mobile/assets/. Re-run after tweaking the palette below.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"

BG = (11, 15, 23, 255)        # #0b0f17
PRIMARY = (31, 111, 235, 255) # #1f6feb
LINE = (255, 255, 255, 255)


def _trend_mark(img: Image.Image, box: tuple[int, int, int, int], rounded: bool) -> None:
    """Draw a rounded primary tile with an upward step-line (rates rising)."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    w = x1 - x0
    if rounded:
        draw.rounded_rectangle(box, radius=int(w * 0.22), fill=PRIMARY)
    # Step-up line across the tile.
    pad = w * 0.2
    pts = []
    steps = [0.78, 0.78, 0.58, 0.58, 0.40, 0.40, 0.22]
    n = len(steps)
    for i, frac in enumerate(steps):
        px = x0 + pad + (w - 2 * pad) * (i / (n - 1))
        py = y0 + (y1 - y0) * frac
        pts.append((px, py))
    draw.line(pts, fill=LINE, width=max(6, int(w * 0.05)), joint="curve")
    # End dot.
    r = max(7, int(w * 0.055))
    ex, ey = pts[-1]
    draw.ellipse((ex - r, ey - r, ex + r, ey + r), fill=LINE)


def make_icon() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), BG)
    inset = int(size * 0.14)
    _trend_mark(img, (inset, inset, size - inset, size - inset), rounded=True)
    img.save(ASSETS / "icon.png")
    # favicon
    img.resize((64, 64)).save(ASSETS / "favicon.png")


def make_adaptive() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Android masks the icon; keep the mark within the centre safe zone (~62%).
    margin = int(size * 0.2)
    _trend_mark(img, (margin, margin, size - margin, size - margin), rounded=True)
    img.save(ASSETS / "adaptive-icon.png")


def make_splash() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = int(size * 0.28)
    _trend_mark(img, (margin, margin, size - margin, size - margin), rounded=True)
    img.save(ASSETS / "splash.png")


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_icon()
    make_adaptive()
    make_splash()
    print(f"Wrote icons to {ASSETS}")
