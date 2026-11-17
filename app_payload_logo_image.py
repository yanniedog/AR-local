"""Normalise provider artwork to a bounded square PNG."""
from __future__ import annotations

import hashlib
import io
import re
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit

CANVAS = 112
MAX_PNG_BYTES = 6144
MAX_SOURCE_PIXELS = 16_000_000
PNG = b"\x89PNG\r\n\x1a\n"
PLACEHOLDER_SHA = "324ff976e7c71dc4749a9d6e78b464ad74fc02cd8ec7b22c97cab88f36903ae8"
_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "ICO")


def is_placeholder(url: str) -> bool:
    path = unquote(urlsplit(url).path).lower()
    return bool(re.search(r"no[-_ ]logo[-_ ]available|(?:^|/)(?:logo[-_])?placeholder[.]", path))


def _svg_png(raw: bytes) -> bytes:
    if len(raw) > 128 * 1024 or re.search(rb"<!DOCTYPE|<!ENTITY|<\?", raw.lstrip().removeprefix(b"<?xml"), re.I):
        raise ValueError("unsafe or oversized SVG")
    root = ET.fromstring(raw)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("expected SVG")
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "style", "image", "feImage"}:
            raise ValueError("unsupported SVG element")
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] in {"href", "src"} and not value.strip().startswith("#"):
                raise ValueError("external SVG reference")
            if any(not ref.strip().startswith("#") for ref in re.findall(r"url\(([^)]*)\)", value, re.I)):
                raise ValueError("external SVG paint")
    return subprocess.run(
        ["rsvg-convert", "--keep-aspect-ratio", "--width", "112", "--height", "112"],
        input=ET.tostring(root, encoding="utf-8"), capture_output=True, timeout=2, check=True,
    ).stdout


def normalize_logo(raw: bytes, *, content_type: str = "") -> bytes:
    from PIL import Image, ImageOps

    if hashlib.sha256(raw).hexdigest() == PLACEHOLDER_SHA:
        raise ValueError("CDR placeholder")
    if "svg" in content_type.lower() or b"<svg" in raw[:1024].lower():
        raw = _svg_png(raw)
    with Image.open(io.BytesIO(raw), formats=_FORMATS) as source:
        if source.width * source.height > MAX_SOURCE_PIXELS or min(source.size) < 8:
            raise ValueError("unsuitable image dimensions")
        image = ImageOps.exif_transpose(source).convert("RGBA")
    bbox = image.getbbox()
    if not bbox:
        raise ValueError("empty image")
    is_transparent = image.getchannel("A").getextrema()[0] < 200
    image = image.crop(bbox)
    if image.getcolors(1) is not None:
        raise ValueError("blank image")
    image.thumbnail((104, 104), Image.Resampling.LANCZOS)
    # Pale artwork needs a dark plate because the app uses a light avatar frame.
    visible = [rgb for *rgb, alpha in image.getdata() if alpha >= 200]
    light = is_transparent and visible and (
        sum(min(rgb) >= 210 for rgb in visible) / len(visible) >= .60
    )
    background = (24, 33, 51, 255) if light else (0, 0, 0, 0)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), background)
    canvas.alpha_composite(image, ((CANVAS - image.width) // 2, (CANVAS - image.height) // 2))
    for colors in (48, 24, 12):
        output = io.BytesIO()
        canvas.quantize(colors=colors, method=Image.Quantize.FASTOCTREE).save(output, "PNG", optimize=True)
        if output.tell() <= MAX_PNG_BYTES:
            return output.getvalue()
    raise ValueError("normalised image exceeds byte budget")
