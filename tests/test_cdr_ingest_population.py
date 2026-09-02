from __future__ import annotations

from cdr_ingest_population import ProductPopulation


def _tracker() -> ProductPopulation:
    return ProductPopulation("provider:v1:" + "a" * 64, "official")


def test_terminal_population_reconciles_declared_total_and_details() -> None:
    tracker = _tracker()
    tracker.page_attempted()
    tracker.page_fetched({"meta": {"totalRecords": 1}})
    assert tracker.product({"productId": "P1", "name": "One"}, "P1")
    tracker.mark_relevant("P1")
    tracker.mark_detail("P1", True)
    tracker.finish_pages(terminal_page_reached=True)
    assert tracker.summary()["state"] == "complete"
    assert tracker.summary()["population_known"] is True


def test_duplicate_even_if_identical_makes_population_unknown() -> None:
    tracker = _tracker()
    product = {"productId": "P1", "name": "One"}
    tracker.page_fetched({"meta": {"totalRecords": 1}})
    assert tracker.product(product, "P1")
    assert not tracker.product(product, "P1")
    tracker.finish_pages(terminal_page_reached=True)
    summary = tracker.summary()
    assert summary["population_known"] is False
    assert summary["duplicate_product_ids"] == ["P1"]


def test_conflicting_duplicate_and_total_mismatch_fail_closed() -> None:
    tracker = _tracker()
    tracker.page_fetched({"meta": {"totalRecords": 2}})
    tracker.product({"productId": "P1", "name": "One"}, "P1")
    tracker.product({"productId": "P1", "name": "Changed"}, "P1")
    tracker.finish_pages(terminal_page_reached=True)
    summary = tracker.summary()
    assert summary["duplicate_conflicts"] == ["P1"]
    assert "declared_total_mismatch" in summary["population_errors"]


def test_missing_terminal_page_or_bad_meta_is_partial() -> None:
    tracker = _tracker()
    tracker.page_attempted()
    tracker.page_fetched({"meta": {"totalRecords": "1"}})
    tracker.finish_pages(terminal_page_reached=False)
    assert tracker.summary()["state"] == "partial"
    assert tracker.summary()["population_known"] is False
