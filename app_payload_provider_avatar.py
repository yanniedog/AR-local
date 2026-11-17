"""Small deterministic PNG monograms for providers without verified artwork."""
from __future__ import annotations

import base64
import re
import struct
import zlib

# Five columns by seven rows, with each row stored as a two-digit hex mask.
_GLYPHS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789?", """
0e11111f111111 1e11111e11111e 0f10101010100f 1e11111111111e
1f10101e10101f 1f10101e101010 0f10101711110f 1111111f111111
0e04040404040e 0702020212120c 11121418141211 1010101010101f
111b1515111111 11191915131311 0e11111111110e 1e11111e101010
0e11111115120d 1e11111e141211 0f10100e01011e 1f040404040404
1111111111110e 11111111110a04 1111111515150a 11110a040a1111
11110a04040404 1f01020408101f 0e11131519110e 040c040404040e
0e11010204081f 1e01010601011e 02060a121f0202 1f10101e01011e
0608101e11110e 1f010204080808 0e11110e11110e 0e11110f01020c
0e110102040004
""".split(), strict=True))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def provider_avatar(short: str, color: str) -> str:
    """Encode a raster image supported by the existing offline app renderer."""
    text = re.sub(r"[^A-Z0-9]", "", short.upper())[:4] or "?"
    glyphs = [bytes.fromhex(_GLYPHS[letter]) for letter in text]
    size, scale = 56, 2
    left = (size - (len(glyphs) * 6 - 1) * scale) // 2
    top = (size - 7 * scale) // 2
    pixels = [bytearray(size) for _ in range(size)]
    for index, glyph in enumerate(glyphs):
        for row, mask in enumerate(glyph):
            for column in range(5):
                if mask & (16 >> column):
                    x = left + (index * 6 + column) * scale
                    y = top + row * scale
                    for line in pixels[y:y + scale]:
                        line[x:x + scale] = b"\x01" * scale
    background = bytes.fromhex(color.removeprefix("#"))
    foreground = b"\xff\xff\xff" if sum(background) < 505 else b"\x0b\x12\x20"
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 3, 0, 0, 0))
    png += _chunk(b"PLTE", background + foreground)
    png += _chunk(b"IDAT", zlib.compress(b"".join(b"\x00" + line for line in pixels)))
    png += _chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
