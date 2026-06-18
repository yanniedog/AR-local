"""Ingest-status rollup (audit P0-retry Phase-4: expose incomplete-ingest status)."""

import json

import cdr_ingest_lib as lib
import cdr_ingest_support as cis
from cdr_ingest_support import FetchResult

ENDPOINT = "http://holder/products"


def test_summarize_failures_rolls_up_by_phase_and_status(tmp_path):
    recs = [
        {"phase": "product_detail", "status": 503},
        {"phase": "product_detail", "status": 503},
        {"phase": "product_detail", "status": "circuit_open"},
        {"phase": "products_index", "status": 500},
    ]
    (tmp_path / "failures.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 4 and s["incomplete"] is True
    assert s["by_phase"] == {"product_detail": 3, "products_index": 1}
    # circuit_open skips are counted distinctly from HTTP errors.
    assert s["by_status"] == {"503": 2, "circuit_open": 1, "500": 1}


def test_summarize_failures_complete_run_has_no_failures(tmp_path):
    s = cis.summarize_failures(tmp_path)  # no failures.jsonl written
    assert s == {"total": 0, "incomplete": False, "by_phase": {}, "by_status": {}}


def test_summarize_failures_skips_blank_and_malformed_lines(tmp_path):
    (tmp_path / "failures.jsonl").write_text(
        '\n{"phase":"product_detail","status":1}\n{not-json\n\n', encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 1 and s["by_status"] == {"1": 1}


def test_detail_worker_crash_is_recorded(tmp_path, monkeypatch):
    # An unexpected exception in a detail worker (not a normal fetch failure) must be
    # recorded so the status rollup counts it, not just logged (Codex).
    failures = []
    monkeypatch.setattr(
        lib, "fetch_cdr_json",
        lambda url, **k: FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4),
    )
    monkeypatch.setattr(
        lib, "extract_products",
        lambda parsed: [{"productId": f"P{i}", "name": f"A{i}"} for i in range(4)],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    monkeypatch.setattr(lib, "classify_product_for_ingest", lambda *a, **k: (next(iter(lib.DATASET_TO_FOLDER)), None))

    def boom(*a, **k):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(lib, "_fetch_bank_detail", boom)
    monkeypatch.setattr(lib, "append_failure", lambda dr, entry, lock=None: failures.append(entry))

    lib.ingest_brand(
        {"endpoint_url": ENDPOINT},
        date_root=tmp_path, resume=False, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name="holder", detail_workers=4, log=lambda *_a, **_k: None,
    )
    assert any(f.get("status") == "worker_crash" for f in failures)


def test_summarize_failures_buckets_missing_or_null_as_unknown(tmp_path):
    recs = [{"bank": "x"}, {"phase": None, "status": None}]
    (tmp_path / "failures.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 2
    assert s["by_phase"] == {"unknown": 2}
    assert s["by_status"] == {"unknown": 2}


def test_summarize_failures_skips_non_object_json_lines(tmp_path):
    # Valid JSON that isn't an object must be skipped, not crash rec.get(...).
    (tmp_path / "failures.jsonl").write_text(
        '[1, 2]\n"a string"\n42\n{"phase":"p","status":1}\n', encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 1 and s["by_status"] == {"1": 1}
