import base64
import hashlib
import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app_payload_build import _core_with_logo_budget, _gzip_bytes
from app_payload_logo_acquisition import _REGISTER, _DIRECTORY, _refresh, resolve_provider_logos
from app_payload_logo_image import normalize_logo


def picture():
    image = Image.new("RGBA", (100, 20))
    ImageDraw.Draw(image).rectangle((1, 2, 98, 17), fill="white")
    ImageDraw.Draw(image).rectangle((31, 4, 35, 9), fill="blue")
    raw = io.BytesIO()
    image.save(raw, "PNG")
    return raw.getvalue()


@pytest.mark.parametrize("register_logo", ["https://images.example/brand", "placeholder", "broken"])
def test_register_first_then_official_site_and_offline_cache(tmp_path, monkeypatch, register_logo):
    import app_payload_logo_acquisition as acquisition

    urls = []
    if register_logo == "placeholder":
        primary = "https://www.cdr.gov.au/sites/default/files/2022-08/No-logo-available-2.png"
    else:
        primary = "https://images.example/brand"
    root = tmp_path / "provider-artwork-v1"
    home = "https://newlender.example/"
    row = {"brandName": "New Lender", "industries": ["non-bank-lending"], "logoUri": primary}
    pages = {
        _REGISTER: json.dumps({"data": [row]}).encode(),
        _DIRECTORY: json.dumps({"value": [{"brands": [{
            "brandName": "New Lender", "participantType": "Data Holder", "status": "ACTIVE", "website": home,
        }]}]}).encode(),
        home: b'<html><img alt="New Lender logo" src="/artwork"></html>',
        home + "artwork": picture(),
        "https://images.example/brand": b'<html>Access denied</html>' if register_logo == "broken" else picture(),
    }

    def fetch(url, **kwargs):
        urls.append(url)
        return SimpleNamespace(url=url, headers={}, body=pages[url])

    monkeypatch.setattr(acquisition, "_get", fetch)
    _refresh(root, ["new-lender"])

    def no_worker(*args, **kwargs):
        pytest.fail("The verified cache must be usable offline")

    monkeypatch.setattr(acquisition.subprocess, "run", no_worker)
    assert (_DIRECTORY in urls) == (register_logo != "https://images.example/brand")
    assert urls[0] == _REGISTER
    if register_logo == "placeholder":
        assert primary not in urls
    else:
        assert urls[1] == primary
    logo = resolve_provider_logos(["New Lender"], {}, tmp_path)["new-lender"]
    image = Image.open(io.BytesIO(base64.b64decode(logo.split(",", 1)[1])))
    assert image.size == (112, 112)
    assert image.convert("RGBA").getpixel((0, 0)) == (24, 33, 51, 255)


def test_worker_failure_and_bad_cache_are_nonfatal(tmp_path, monkeypatch):
    import app_payload_logo_acquisition as acquisition

    root = tmp_path / "provider-artwork-v1"
    root.mkdir()
    (root / (hashlib.sha256(b"new-lender").hexdigest() + ".json")).write_text(
        '{"png":"invalid"}', encoding="utf-8"
    )

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("logo worker", 18)

    monkeypatch.setattr(acquisition.subprocess, "run", timeout)
    assert resolve_provider_logos(["New Lender"], {}, tmp_path) == {}


def test_svg_external_reference_is_rejected_before_rasterisation():
    with pytest.raises(ValueError):
        normalize_logo(b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/remote"/></svg>')


def test_core_budget_falls_back_to_square_monogram():
    random_bytes = hashlib.shake_256(b"test").digest(4096)
    logo = "data:image/png;base64," + base64.b64encode(random_bytes).decode()
    core = {"brands": {"Example": {"logo": logo, "logo_source": "artwork", "short": "E", "color": "#123456"}}}
    result, wire = _core_with_logo_budget(core, len(_gzip_bytes(core)) - 1)
    assert result["brands"]["Example"]["logo_source"] == "monogram"
    assert len(wire) < len(_gzip_bytes(core))
    assert core["brands"]["Example"]["logo_source"] == "artwork"
