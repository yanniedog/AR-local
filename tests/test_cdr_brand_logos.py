"""Tests for CDR Register brand logos (cdr_brand_logos.py)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import cdr_brand_logos
from app_payload import build_brands

REGISTER = {
    "amp bank": "https://amp.example/amp.png",
    "amp bank go": "https://amp.example/amp-go.png",
    "mystate bank": "https://mystate.example/logo.png",
    "ing": "https://ing.example/logo.jpg",
}


def _raw(entries):
    return json.dumps({"data": entries}).encode("utf-8")


def test_parse_filters_unrenderable_and_insecure() -> None:
    parsed = cdr_brand_logos.parse_register_payload(
        _raw(
            [
                {"brandName": "MyState Bank", "logoUri": "https://x/logo.png"},
                {"brandName": "SVG Bank", "logoUri": "https://x/logo.svg"},
                {"brandName": "Ashx Bank", "logoUri": "https://x/logo.ashx?h=90"},
                {"brandName": "Http Bank", "logoUri": "http://x/logo.png"},
                {"brandName": "Query Bank", "logoUri": "https://x/logo.png?format=1500w"},
                {"brandName": "", "logoUri": "https://x/logo.png"},
            ]
        )
    )
    assert parsed == {
        "mystate bank": "https://x/logo.png",
        "query bank": "https://x/logo.png?format=1500w",
    }


def test_exact_match_beats_token_subset() -> None:
    assert cdr_brand_logos.logo_uri_for("AMP Bank", REGISTER) == "https://amp.example/amp.png"
    assert (
        cdr_brand_logos.logo_uri_for("AMP Bank GO", REGISTER) == "https://amp.example/amp-go.png"
    )


def test_token_subset_handles_legal_suffixes() -> None:
    # Generic tokens (bank/australia/ltd) are stripped, so ING's register entry
    # matches and "Bank Australia" can never steal it.
    assert (
        cdr_brand_logos.logo_uri_for("ING BANK (Australia) Ltd", REGISTER)
        == "https://ing.example/logo.jpg"
    )
    assert cdr_brand_logos.logo_uri_for("ING", REGISTER) == "https://ing.example/logo.jpg"
    assert cdr_brand_logos.logo_uri_for("MyState Bank Ltd", REGISTER) == (
        "https://mystate.example/logo.png"
    )
    assert cdr_brand_logos.logo_uri_for("Unknown Bank", REGISTER) is None


def test_fetch_uses_cache_and_survives_failure(tmp_path: Path) -> None:
    cache = tmp_path / "logos.json"
    calls = {"n": 0}

    def fetcher(_timeout: int) -> bytes:
        calls["n"] += 1
        return _raw([{"brandName": "MyState Bank", "logoUri": "https://x/logo.png"}])

    first = cdr_brand_logos.fetch_register_logos(cache, fetcher=fetcher)
    assert first == {"mystate bank": "https://x/logo.png"}
    second = cdr_brand_logos.fetch_register_logos(cache, fetcher=fetcher)
    assert second == first
    assert calls["n"] == 1  # second call served from cache

    def broken(_timeout: int) -> bytes:
        raise OSError("register down")

    stale = time.time() - cdr_brand_logos.CACHE_MAX_AGE_SEC - 1
    import os

    os.utime(cache, (stale, stale))
    assert cdr_brand_logos.fetch_register_logos(cache, fetcher=broken) == {}


def test_build_brands_attaches_register_uri_only_without_embedded_logo() -> None:
    brands = build_brands(
        ["MyState Bank", "ING"],
        shortcodes={},
        logos={"ing": "data:image/png;base64,abc"},
        register_logos=REGISTER,
    )
    assert brands["MyState Bank"]["logo_uri"] == "https://mystate.example/logo.png"
    assert "logo_uri" not in brands["ING"]
    assert brands["ING"]["logo"] == "data:image/png;base64,abc"
