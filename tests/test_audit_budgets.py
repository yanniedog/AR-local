"""Phase-0 resource-budget guards from the consolidated audit.

The audit's #1 sequencing item was "lock in resource budgets" — probes that FAIL
when a key threshold regresses, so the expensive data paths can't silently drift
back. These cover the budgets checkable in-process (server-side); the device /
latency budgets live with the mobile + Pi smoke checks.
"""

import gzip
import json
from datetime import date, timedelta

import cdr_ingest_support as cis
import cdr_ribbon_normalize as crn

# History serving payload (audit: 90-day window must stay well under these, vs the
# old ~113 MB raw-row transport the compact contract replaced).
MAX_DECODED_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_GZIP_BYTES = 2 * 1024 * 1024      # 2 MB
# One CDR logical fetch must not exceed the shared attempt budget across versions.
MAX_CDR_ATTEMPTS = 8


def test_compact_history_serving_payload_within_budget():
    # A generous 90-day window with many providers; the compact aggregate must stay
    # far under the audit's serving budget.
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(90)]
    providers = [f"Provider {i:03d}" for i in range(50)]
    rows = []
    for p in providers:
        for k in range(3):
            rows.append({
                "product_key": f"{p}-{k}",
                "provider": p,
                "rate": f"{4 + k * 0.1:.2f}",
                "comparison_rate": f"{4.1 + k * 0.1:.2f}",
            })
    # Same catalogue each day here, so aggregate once and reuse across the window
    # (Gemini) — compact_history only reads each day's aggregate.
    daily = crn.aggregate_ribbon(rows, "Mortgage")
    aggregates = {d: daily for d in dates}

    # Measure the served shape: cdr_dashboard_server.bank_history_compact_payload
    # serves a small envelope wrapping compact_history(...). (That handler is a
    # nested closure that reads SQLite, so it isn't unit-callable here; this guards
    # the compact aggregate that constitutes ~all of the served bytes, and asserts
    # the served history payload carries NO raw per-product rows.)
    served = {
        "run_date": dates[-1],
        "section": "Mortgage",
        "include_non_standard": False,
        **crn.compact_history(dates, aggregates),
    }
    assert "rates" not in served and "products" not in served, "served history must stay compact"
    blob = json.dumps(served, separators=(",", ":")).encode("utf-8")
    assert len(blob) < MAX_DECODED_BYTES, f"decoded {len(blob)} >= budget {MAX_DECODED_BYTES}"
    assert len(gzip.compress(blob)) < MAX_GZIP_BYTES, "gzip transfer over budget"


def test_cdr_logical_fetch_capped_at_attempt_budget(monkeypatch):
    # A persistent 5xx must not exceed the shared attempt budget for one logical
    # fetch (the audit's amplification guard: 6 versions x 7 retries = 42 -> <= 8).
    monkeypatch.setattr(cis.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def fake_http(url, headers, *, timeout):
        calls["n"] += 1
        return 503, "", None

    monkeypatch.setattr(cis, "http_request", fake_http)
    res = cis.fetch_cdr_json("http://x", timeout=1, max_retries=6, sleep_ms=0)
    assert res.attempts <= MAX_CDR_ATTEMPTS
    assert calls["n"] <= MAX_CDR_ATTEMPTS
