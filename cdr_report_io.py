"""Bounded JSON decoding shared by read-only report and history tools."""
import gzip
import io
import json

MAX_ASSET_BYTES = 16 * 1024**2
MAX_PLAIN_BYTES = 96 * 1024**2


def decode_json(body: bytes, *, compressed: bool, max_plain=MAX_PLAIN_BYTES):
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            plain = stream.read(max_plain + 1)
    else:
        plain = body
    if len(plain) > max_plain:
        raise ValueError('expanded JSON exceeds bound')
    return json.loads(plain)
