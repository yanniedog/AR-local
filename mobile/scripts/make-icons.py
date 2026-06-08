"""Generate the app icon / adaptive icon / splash / favicon for AR Rates.

Pure-PIL, deterministic. Run from anywhere:

    python mobile/scripts/make-icons.py

Writes PNGs into mobile/assets/. Re-run after tweaking the palette below.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"

BG = (11, 15, 23, 255)          # #0b0f17  app/splash background (navy)
PRIMARY = (59, 130, 246, 255)   # #3b82f6  AR-local blue
PRIMARY_HI = (96, 165, 250, 255)  # #60a5fa lighter blue
LINE = (255, 255, 255, 255)
INK = (4, 18, 43, 255)          # deep navy for marks on the blue tile


def _trend_mark(img: Image.Image, box: tuple[int, int, int, int], rounded: bool) -> None:
    """A rounded AR-local-blue tile with the 'ribbon' motif: a distribution bar with
    a median marker plus three ascending rate bars — the AR-local dashboard signature."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    w = x1 - x0
    hgt = y1 - y0
    if rounded:
        draw.rounded_rectangle(box, radius=int(w * 0.225), fill=PRIMARY)

    padx = w * 0.18
    inner_w = w - 2 * padx
    # Three ascending rounded bars (a mini rate chart).
    bar_n = 3
    gap = inner_w * 0.10
    bar_w = (inner_w - gap * (bar_n - 1)) / bar_n
    base_y = y0 + hgt * 0.74
    heights = [0.26, 0.40, 0.56]
    for i, hf in enumerate(heights):
        bx = x0 + padx + i * (bar_w + gap)
        top = base_y - hgt * hf
        col = LINE if i < bar_n - 1 else (255, 255, 255, 255)
        draw.rounded_rectangle((bx, top, bx + bar_w, base_y), radius=int(bar_w * 0.32), fill=col)

    # The ribbon: a rounded distribution bar beneath the chart with a median dot.
    rib_y0 = y0 + hgt * 0.80
    rib_y1 = y0 + hgt * 0.875
    draw.rounded_rectangle((x0 + padx, rib_y0, x1 - padx, rib_y1), radius=int((rib_y1 - rib_y0) / 2), fill=INK)
    # median marker
    mx = x0 + padx + inner_w * 0.62
    r = (rib_y1 - rib_y0) * 0.95
    cy = (rib_y0 + rib_y1) / 2
    draw.ellipse((mx - r, cy - r, mx + r, cy + r), fill=LINE)


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
