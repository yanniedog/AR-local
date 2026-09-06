"""Model the stale public redirect observed after September 6 asset replacement."""

import io
import json
import urllib.parse
import urllib.request

import pytest

import app_payload_publish as publisher
import app_payload_v2 as v2
import pi_payload_freshness as freshness


@pytest.mark.parametrize("reader", [
    lambda: freshness.fetch_document(freshness.MANIFEST_URL),
    lambda: publisher._live_manifest_status("yanniedog/AR-local", "app-payload-latest")[1],
    lambda: v2._live_v2_manifest_status("yanniedog/AR-local", "app-payload-latest")[1],
])
def test_replaced_manifest_is_not_read_through_an_old_redirect(monkeypatch, reader):
    live = {"run_date": "2026-09-05"}
    cached_redirects = {}

    def open_cached(url, **kwargs):
        address = url.full_url if isinstance(url, urllib.request.Request) else url
        # Cache-Control did not invalidate GitHub's old redirect in the incident.
        raw = cached_redirects.setdefault(address, json.dumps(live).encode())
        return io.BytesIO(raw)

    monkeypatch.setattr(urllib.request, "urlopen", open_cached)
    assert reader()["run_date"] == "2026-09-05"
    live["run_date"] = "2026-09-06"
    assert reader()["run_date"] == "2026-09-06"


def test_index_refresh_preserves_supplied_query_and_fragment(monkeypatch):
    seen = []

    def fetch(request, **kwargs):
        seen.append(urllib.parse.urlsplit(request.full_url))
        return io.BytesIO(b'{"latest_date":"2026-09-06"}')

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    url = freshness.DATES_INDEX_URL + "?source=app%20check#receipt"
    assert freshness.fetch_document(url)["latest_date"] == "2026-09-06"
    assert seen[0].fragment == "receipt"
    assert urllib.parse.parse_qs(seen[0].query)["source"] == ["app check"]
    assert urllib.parse.parse_qs(seen[0].query)["_"]
