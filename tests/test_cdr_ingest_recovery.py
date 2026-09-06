"""Recovery control tests using September 7 preserved provider responses."""
import json
import hashlib
from pathlib import Path

from cdr_ingest_recovery import _index_captured, _reconcile, recover_transient_providers

CAPTURE = Path(__file__).parent / "fixtures" / "cdr-september7"


def failures():
    return [{"bank": row["provider"], "phase": row["phase"], "status": row["status"],
             "snippet": row["body"]} for row in json.loads((CAPTURE / "failures.json").read_text())]


def journal(root, rows):
    (root / "failures.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_no_retry_of_deterministic_source_errors(tmp_path):
    rows = failures()
    for row in rows:
        row["retryable"] = False
    journal(tmp_path, rows)
    result = recover_transient_providers(tmp_path, [({}, row["bank"]) for row in rows],
                                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()), log=lambda _: None)
    assert result["result"] == "not_needed"
    assert len((tmp_path / "failures.jsonl").read_text().splitlines()) == len(rows)


def test_attempts_bounded_and_original_failures_retained(tmp_path):
    row = next(row for row in failures() if row["bank"] == "Family First")
    journal(tmp_path, [row])
    calls = []
    result = recover_transient_providers(tmp_path, [({}, row["bank"])],
                                        lambda item, **kw: calls.append(kw), log=lambda _: None, sleep=lambda _: None)
    assert len(calls) == 1 and "recovery_deadline" in calls[0]
    assert result["remaining_failures"] == 1  # no positive successful index proof
    assert hashlib.sha256(result["initial_failure_journal"].encode()).hexdigest() == result["initial_failure_sha256"]
    assert len(list((tmp_path / "_recovery").glob("failures-*.jsonl"))) == 1


def test_recovery_crash_does_not_erase_failure_evidence(tmp_path):
    row = next(row for row in failures() if row["bank"] == "Family First")
    journal(tmp_path, [row])
    def crash(*a, **kw):
        raise RuntimeError("interrupted")
    result = recover_transient_providers(tmp_path, [({}, row["bank"])], crash,
                                        log=lambda _: None, sleep=lambda _: None)
    assert result["result"] == "recovery_error" and result["remaining_failures"] == 1


def test_budget_prevents_second_provider(tmp_path):
    rows = [row for row in failures() if row["bank"] in {"Family First", "DDH Graham"}]
    journal(tmp_path, rows)
    times = iter([0, 0, 181])
    calls = []
    result = recover_transient_providers(tmp_path, [({}, row["bank"]) for row in rows],
                                        lambda item, **kw: calls.append(item), log=lambda _: None,
                                        clock=lambda: next(times), sleep=lambda _: None)
    assert result["result"] == "budget_exhausted" and len(calls) == 1


def test_only_proven_recovered_detail_is_removed(tmp_path):
    body = json.loads((CAPTURE / "defence.json").read_text())["product_detail"]["body"]
    pid = body["data"]["productId"]
    row = {"bank": "Defence Bank", "phase": "product_detail", "product_id": pid, "status": 503}
    assert _reconcile(tmp_path, [row], [row], "Defence Bank") == [row]
    leaf = tmp_path / "Savings" / "Defence Bank" / "captured" / "product"
    leaf.mkdir(parents=True)
    (leaf / "product-id.txt").write_text(pid)
    (leaf / "product-detail.json").write_text(json.dumps(body))
    assert _reconcile(tmp_path, [row], [row], "Defence Bank") == []
    row["phase"] = "classification_detail"
    assert _reconcile(tmp_path, [row], [row], "Defence Bank") == []


def test_other_provider_failure_survives_recovery(tmp_path):
    rows = failures()[:2]
    fresh = {**rows[0], "status": "recovery_budget_exhausted"}
    result = _reconcile(tmp_path, rows, rows + [fresh], rows[0]["bank"])
    assert rows[1] in result and fresh in result


def test_corrupt_journal_is_not_rewritten(tmp_path):
    (tmp_path / "failures.jsonl").write_text("{broken")
    result = recover_transient_providers(tmp_path, [], lambda *a: None, log=lambda _: None)
    assert result["result"] == "invalid_failure_evidence"
    assert (tmp_path / "failures.jsonl").read_text() == "{broken"


def test_recovered_shorter_index_ignores_but_preserves_old_failed_page(tmp_path):
    body = json.loads((CAPTURE / "defence.json").read_text())["products_index"]["body"]
    # Keep the real products; vary only pagination to reproduce a shorter listing.
    body["meta"] = {"totalRecords": len(body["data"]["products"]), "totalPages": 1}
    body["links"].pop("next", None)
    pages = tmp_path / "_holders" / "Defence Bank" / "_products-index"
    pages.mkdir(parents=True)
    (pages / "page-0001.json").write_text(json.dumps(body))
    stale = b'{"errors":[{"code":"503","title":"Temporarily unavailable"}]}'
    (pages / "page-0002.json").write_bytes(stale)
    failure = {"bank": "Defence Bank", "phase": "products_index", "status": 503}

    assert _index_captured(tmp_path, "Defence Bank")
    assert _reconcile(tmp_path, [failure], [failure], "Defence Bank") == []
    assert (pages / "page-0002.json").read_bytes() == stale


def test_incomplete_current_index_does_not_clear_old_failure(tmp_path):
    body = json.loads((CAPTURE / "defence.json").read_text())["products_index"]["body"]
    pages = tmp_path / "_holders" / "Defence Bank" / "_products-index"
    pages.mkdir(parents=True)
    (pages / "page-0001.json").write_text(json.dumps(body))
    (pages / "page-0002.json").write_text('{"errors":[{"code":"503"}]}')
    failure = {"bank": "Defence Bank", "phase": "products_index", "status": 503}

    assert not _index_captured(tmp_path, "Defence Bank")
    assert _reconcile(tmp_path, [failure], [failure], "Defence Bank") == [failure]
