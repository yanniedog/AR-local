"""Acquire unresolved provider logos without making artwork a publication gate."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from app_payload_logo_image import CANVAS, MAX_PNG_BYTES, PNG, is_placeholder, normalize_logo
from cdr_atomic import atomic_write_json
from cdr_http_policy import HttpPolicy, canonical_https_url, request_https, sanitize_url

_REGISTER = "https://api.cdr.gov.au/cdr-register/v1/all/data-holders/brands/summary"
_DIRECTORY = "https://api.cdr.gov.au/public-register/v1/participants"
_POLICY = HttpPolicy(max_compressed_bytes=2 << 20, max_inflated_bytes=2 << 20, max_body_bytes=2 << 20)
_RETRY_SECONDS = 20 * 3600
_MAX_PER_RUN = 12
_WORKER_SECONDS = 18


def logo_key(provider: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", provider.lower()).strip("-")


class _SiteArtwork(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "link":
            rel = (fields.get("rel") or "").lower().split()
            if "apple-touch-icon" in rel or "icon" in rel:
                self.images.append((1 if "apple-touch-icon" in rel else 2, fields.get("href")))
        if tag == "img":
            label = " ".join(fields.get(k) or "" for k in ("alt", "class", "id", "src"))
            if re.search(r"\blogo\b", label, re.I):
                self.images.append((0, fields.get("src")))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def _site_homes(row):
    for field in ("websiteUri", "websiteUrl", "website"):
        if row.get(field):
            return [(row[field], False)]
    host = urlsplit(row.get("publicBaseUri") or row.get("productBaseUri") or "").hostname or ""
    # Remove only service labels. The title must independently identify the
    # brand before artwork from an inferred homepage is accepted.
    labels = host.split(".")
    while len(labels) > 2 and re.fullmatch(r"(?:public|prd|api[0-9]*|ob|cdr[0-9]*|open[-]?banking)", labels[0]):
        labels.pop(0)
    host = ".".join(labels)
    if not host:
        return []
    return [(f"https://{candidate}/", True) for candidate in dict.fromkeys((host, "www." + host))
            if not candidate.startswith("www.www.")]


def _get(url, *, accept, headers=None):
    response = request_https(url, {"accept": accept, "user-agent": "AustralianRates/1.0", **(headers or {})},
                             timeout=3.5, policy=_POLICY)
    if response.status != 200:
        raise ValueError(f"HTTP {response.status}")
    return response


def _image(url):
    if not url or is_placeholder(url):
        raise ValueError("no provider artwork at URL")
    response = _get(url, accept="image/*")
    if is_placeholder(response.url):
        raise ValueError("redirected to a placeholder")
    return normalize_logo(response.body, content_type=response.headers.get("content-type", "")), response.url


def _official_logo(row, website=None):
    brand = logo_key(row["brandName"])
    homes = ([(website, False)] if website else []) + _site_homes(row)
    for home, inferred in dict.fromkeys(homes):
        try:
            site = _get(home, accept="text/html")
            page = _SiteArtwork()
            page.feed(site.body.decode("utf-8", errors="replace"))
            if inferred and f"-{brand}-" not in f"-{logo_key(page.title)}-":
                continue
            site_origin = canonical_https_url(site.url).origin
            candidates = sorted({(rank, urljoin(site.url, link)) for rank, link in page.images if link})
            for _, url in candidates[:4]:
                try:
                    if canonical_https_url(url).origin == site_origin:
                        return _image(url)
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _candidate(row, official_website):
    try:
        image, source = _image(row.get("logoUri"))
        return image, source, "cdr-register"
    except Exception:
        result = _official_logo(row, official_website(logo_key(row["brandName"])))
        return (*result, "official-site") if result else None


def _cache_path(root, key):
    return root / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")


def _cache_read(root, key):
    try:
        path = _cache_path(root, key)
        with path.open("rb") as stream:
            record = json.loads(stream.read(12 * 1024))
        value = record.get("png", "")
        if value:
            image = base64.b64decode(value, validate=True)
            size = CANVAS.to_bytes(4, "big") * 2
            if (len(image) > MAX_PNG_BYTES or not image.startswith(PNG) or image[16:24] != size
                    or hashlib.sha256(image).hexdigest() != record.get("sha256")):
                raise ValueError("invalid cached logo")
        return value, path.stat().st_mtime
    except (OSError, ValueError, AttributeError, TypeError):
        return "", 0


def _official_websites():
    """Read the brand websites published by the ACCC's Find a Provider directory."""
    try:
        directory = _get(_DIRECTORY, accept="application/json")
        participants = json.loads(directory.body)["value"]
        sites = {}
        for participant in participants:
            for brand in participant.get("brands") or ():
                if (brand.get("participantType") == "Data Holder"
                        and brand.get("status") == "ACTIVE" and brand.get("website")):
                    sites.setdefault(logo_key(brand["brandName"]), set()).add(brand["website"])
        return {key: next(iter(urls)) for key, urls in sites.items() if len(urls) == 1}
    except Exception:
        return {}


def _refresh(root, keys):
    register = _get(_REGISTER, accept="application/json", headers={"x-v": "2"})
    entries = {}
    for row in json.loads(register.body)["data"]:
        if {"banking", "non-bank-lending"}.intersection(row.get("industries", ())):
            entries.setdefault(logo_key(row["brandName"]), []).append(row)
    directory = None

    def website(key):
        nonlocal directory
        if directory is None:
            directory = _official_websites()
        return directory.get(key)

    for key in keys:
        if _cache_read(root, key)[0]:
            continue
        atomic_write_json(_cache_path(root, key + ":retry"), {})
        rows = entries.get(key, ())
        try:
            result = _candidate(rows[0], website) if len(rows) == 1 else None
        except (ValueError, TypeError):
            continue
        record = {}
        if result:
            image, source, kind = result
            record = {
                "png": base64.b64encode(image).decode("ascii"), "source": sanitize_url(source),
                "source_kind": kind, "sha256": hashlib.sha256(image).hexdigest(),
            }
        if record:
            atomic_write_json(_cache_path(root, key), record)


def resolve_provider_logos(providers, known, state_dir: Path | None):
    if state_dir is None:
        return {}
    root = state_dir / "provider-artwork-v1"
    keys = sorted({logo_key(provider) for provider in providers} - known.keys() - {""})
    result, pending = {}, []
    for key in keys:
        encoded, _ = _cache_read(root, key)
        if encoded:
            result[key] = "data:image/png;base64," + encoded
        else:
            _, attempted = _cache_read(root, key + ":retry")
            if time.time() - attempted >= _RETRY_SECONDS:
                pending.append((attempted, key))
    requested = [key for _, key in sorted(pending)[:_MAX_PER_RUN]]
    if requested:
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), str(root)],
                           input=json.dumps(requested), text=True, timeout=_WORKER_SECONDS,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"[app_payload] provider artwork refresh incomplete: {type(error).__name__}", flush=True)
        for key in requested:
            encoded, _ = _cache_read(root, key)
            if encoded:
                result[key] = "data:image/png;base64," + encoded
    return result


if __name__ == "__main__":
    _refresh(Path(sys.argv[1]), json.load(sys.stdin))
