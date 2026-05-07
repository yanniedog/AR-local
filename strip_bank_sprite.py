"""Remove dark sprite background; optional strip near-white tile frame from edges."""
from __future__ import annotations

import argparse
from collections import deque

from PIL import Image, ImageDraw


def strip_dark_background(im: Image.Image, thresh: float = 45.0) -> Image.Image:
    im = im.convert("RGBA")
    ImageDraw.floodfill(im, (0, 0), (0, 0, 0, 0), thresh=thresh)
    return im


def strip_nearwhite_from_transparent_edge(
    im: Image.Image,
    lum_thresh: float = 248.0,
    edge_radius: int = 4,
) -> Image.Image:
    """Remove high-luminance pixels connected to outside through near-white."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    alpha = [[0] * w for _ in range(h)]
    lum = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            alpha[y][x] = a
            lum[y][x] = (r + g + b) / 3.0

    near_out = [[False] * w for _ in range(h)]
    r0 = edge_radius
    for y in range(h):
        for x in range(w):
            if alpha[y][x] != 0:
                continue
            y1, y2 = max(0, y - r0), min(h, y + r0 + 1)
            x1, x2 = max(0, x - r0), min(w, x + r0 + 1)
            for yy in range(y1, y2):
                for xx in range(x1, x2):
                    near_out[yy][xx] = True

    stripped = [[False] * w for _ in range(h)]
    q: deque[tuple[int, int]] = deque()
    for y in range(h):
        for x in range(w):
            if alpha[y][x] == 0 or lum[y][x] < lum_thresh or not near_out[y][x]:
                continue
            stripped[y][x] = True
            q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = x + dx, y + dy
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if (
                stripped[ny][nx]
                or alpha[ny][nx] == 0
                or lum[ny][nx] < lum_thresh
            ):
                continue
            stripped[ny][nx] = True
            q.append((nx, ny))

    for y in range(h):
        for x in range(w):
            if stripped[y][x]:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return im


def _count_opaque(im: Image.Image) -> tuple[int, int]:
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    n = 0
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:
                n += 1
    return n, w * h


def main() -> None:
    p = argparse.ArgumentParser(
        description="Remove dark background from bank logo sprite PNG."
    )
    p.add_argument("input", nargs="?", help="Input PNG path")
    p.add_argument(
        "-o",
        "--output",
        default="bank-sprite-transparent.png",
        help="Output PNG path",
    )
    p.add_argument(
        "--thresh",
        type=float,
        default=45.0,
        help="Flood-fill color distance threshold for background",
    )
    p.add_argument(
        "--strip-white-tiles",
        action="store_true",
        help="Also remove near-white regions connected to outside (tile frames)",
    )
    p.add_argument(
        "--white-lum",
        type=float,
        default=248.0,
        help="Mean RGB threshold for white-tile strip pass",
    )
    p.add_argument(
        "--edge-radius",
        type=int,
        default=4,
        help="How far from transparency to seed white-tile removal (px)",
    )
    args = p.parse_args()
    inp = args.input
    if not inp:
        raise SystemExit("input path required")

    im = Image.open(inp)
    im = strip_dark_background(im, thresh=args.thresh)
    if args.strip_white_tiles:
        im = strip_nearwhite_from_transparent_edge(
            im,
            lum_thresh=args.white_lum,
            edge_radius=args.edge_radius,
        )
    im.save(args.output)
    opaque, total = _count_opaque(im)
    print(f"wrote {args.output} opaque_pixels={opaque}/{total}")


if __name__ == "__main__":
    main()
