"""Ingest-status rollup (audit P0-retry Phase-4: expose incomplete-ingest status)."""

import json

import cdr_ingest_support as cis


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
