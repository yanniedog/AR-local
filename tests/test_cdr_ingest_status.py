"""Ingest-status rollup (audit P0-retry Phase-4: expose incomplete-ingest status)."""

import json
from pathlib import Path

import pytest

import cdr_daily
import cdr_ingest_lib as lib
import cdr_ingest_support as cis
from cdr_ingest_support import FetchResult

ENDPOINT = "http://holder/products"


@pytest.mark.parametrize("value", ("../2026-09-02", "2026-9-2", "not-a-date"))
def test_run_date_rejects_noncanonical_or_escaping_values(value):
    with pytest.raises(SystemExit):
        lib.parse_args(["--date", value])


def _brand(endpoint=ENDPOINT):
    return {
        "endpoint_url": endpoint,
        "brand_name": "Holder",
        "legal_entity_name": "Holder Ltd",
        "provider_uid": "provider-fallback:v1:" + "a" * 64,
        "provider_identity_status": "fallback",
        "data_holder_id": "",
        "data_holder_brand_id": "",
    }


def _snapshot(*, ok=True, complete=True, brands=None):
    return cis.RegisterSnapshot(
        register_ok=ok,
        register_provenance_complete=complete,
        register_attempts=[
            {
                "source_url": "https://register.example/source",
                "mode": "plain",
                "ok": ok,
                "status": 200 if ok else 599,
                "bytes": 2 if ok else 0,
                "sha256": "0" * 64,
            }
        ],
        banking_brands=list(brands or []),
        banking_count_before_filter=len(brands or []),
    )


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


def test_register_failure_still_publishes_verified_attempt_journal_status(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        lib,
        "collect_register_snapshot",
        lambda **_kwargs: _snapshot(ok=False, complete=False),
    )

    exit_code = lib.main(
        [
            "--out",
            str(tmp_path),
            "--date",
            "2026-08-15",
            "--workers",
            "1",
            "--detail-workers",
            "1",
        ]
    )

    assert exit_code == 2
    status = json.loads(
        (tmp_path / "2026-08-15" / "banks" / "ingest-status.json").read_text(
            encoding="utf-8"
        )
    )
    journal = status["raw_attempt_journal"]
    assert journal["attempts"] == 0
    assert journal["verified"] is True
    assert journal["path"].startswith("_raw-attempt-journals-v1/")
    assert journal["path_resolution"] == "relative_to_ingest_run_root"
    assert journal["retention"] == "follows_ingest_run_root"
    assert status["incomplete"] is True


def test_successful_run_status_points_to_verified_attempt_journal(tmp_path, monkeypatch):
    brand = _brand("https://holder.example/products")
    monkeypatch.setattr(
        lib,
        "collect_register_snapshot",
        lambda **_kwargs: _snapshot(brands=[brand]),
    )
    def fake_ingest(_brand_row, *, date_root, bank_dir_name, **_kwargs):
        summary = date_root / "_holders" / bank_dir_name / "_products-index" / "index-summary.json"
        summary.parent.mkdir(parents=True)
        summary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider_uid": brand["provider_uid"],
                    "state": "empty",
                    "population_known": True,
                    "unique_product_ids": 0,
                    "relevant_products": 0,
                    "details_present": 0,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(lib, "ingest_brand", fake_ingest)

    exit_code = lib.main(
        [
            "--out",
            str(tmp_path),
            "--date",
            "2026-08-15",
            "--workers",
            "1",
            "--detail-workers",
            "1",
        ]
    )

    assert exit_code == 0
    status = json.loads(
        (tmp_path / "2026-08-15" / "banks" / "ingest-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["raw_attempt_journal"]["verified"] is True
    assert status["providers_attempted"] == 1
    assert status["incomplete"] is False


def test_unresolved_classification_withholds_the_observation(tmp_path, monkeypatch):
    brand = _brand("https://holder.example/products")
    monkeypatch.setattr(
        lib,
        "collect_register_snapshot",
        lambda **_kwargs: _snapshot(brands=[brand]),
    )

    def fake_ingest(_brand_row, *, date_root, bank_dir_name, **_kwargs):
        summary = (
            date_root
            / "_holders"
            / bank_dir_name
            / "_products-index"
            / "index-summary.json"
        )
        summary.parent.mkdir(parents=True)
        summary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider_uid": brand["provider_uid"],
                    "state": "partial",
                    "population_known": True,
                    "unique_product_ids": 1,
                    "relevant_products": 0,
                    "out_of_scope_products": 0,
                    "classification_unresolved": ["P1"],
                    "details_present": 0,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(lib, "ingest_brand", fake_ingest)

    assert lib.main(
        [
            "--out",
            str(tmp_path),
            "--date",
            "2026-08-15",
            "--workers",
            "1",
            "--detail-workers",
            "1",
        ]
    ) == 2
    status = json.loads(
        (tmp_path / "2026-08-15" / "banks" / "ingest-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["classification_unresolved_products"] == 1
    assert status["coverage_evidence_complete"] is False
    assert status["provider_states"][0]["products_discovered"] == 1
    assert status["provider_states"][0]["products_in_scope"] == 0


def test_unknown_population_withholds_the_observation(tmp_path, monkeypatch):
    brand = _brand("https://holder.example/products")
    monkeypatch.setattr(
        lib,
        "collect_register_snapshot",
        lambda **_kwargs: _snapshot(brands=[brand]),
    )

    def fake_ingest(_brand_row, *, date_root, bank_dir_name, **_kwargs):
        summary = (
            date_root
            / "_holders"
            / bank_dir_name
            / "_products-index"
            / "index-summary.json"
        )
        summary.parent.mkdir(parents=True)
        summary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider_uid": brand["provider_uid"],
                    "state": "partial",
                    "population_known": False,
                    "unique_product_ids": 1,
                    "relevant_products": 1,
                    "out_of_scope_products": 0,
                    "classification_unresolved": [],
                    "details_present": 1,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(lib, "ingest_brand", fake_ingest)

    assert lib.main(
        [
            "--out",
            str(tmp_path),
            "--date",
            "2026-08-15",
            "--workers",
            "1",
            "--detail-workers",
            "1",
        ]
    ) == 2
    status = json.loads(
        (tmp_path / "2026-08-15/banks/ingest-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["coverage_evidence_complete"] is False
    assert status["provider_states"][0]["population_known"] is False


def test_cross_origin_pagination_is_recorded_and_not_followed(tmp_path, monkeypatch):
    failures = []
    monkeypatch.setattr(
        lib,
        "fetch_cdr_json",
        lambda url, **_kwargs: FetchResult(
            ok=True,
            status=200,
            url=url,
            text='{"data":{},"links":{"next":"https://evil.example/products?page=2"}}',
            version=4,
        ),
    )
    monkeypatch.setattr(lib, "extract_products", lambda _parsed: [])
    monkeypatch.setattr(
        lib,
        "append_failure",
        lambda _root, entry, lock=None: failures.append(entry),
    )

    lib.ingest_brand(
        _brand("https://holder.example/products"),
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=None,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_args: None,
    )

    assert [item["status"] for item in failures] == ["pagination_cross_origin"]


def test_summarize_failures_complete_run_has_no_failures(tmp_path):
    (tmp_path / "failures.jsonl").write_text("", encoding="utf-8")
    s = cis.summarize_failures(tmp_path)
    assert s == {
        "total": 0,
        "corrupt_records": 0,
        "unattributed_records": 0,
        "failure_log_readable": True,
        "failure_provenance_complete": True,
        "incomplete": False,
        "by_phase": {},
        "by_status": {},
        "by_provider": {},
    }


def test_summarize_failures_missing_log_is_incomplete(tmp_path):
    summary = cis.summarize_failures(tmp_path)
    assert summary["failure_log_readable"] is False
    assert summary["failure_provenance_complete"] is False
    assert summary["incomplete"] is True


def test_summarize_failures_unreadable_log_is_incomplete(tmp_path, monkeypatch):
    failure_log = tmp_path / "failures.jsonl"
    failure_log.write_text("", encoding="utf-8")
    real_open = Path.open

    def deny_failure_log(path, *args, **kwargs):
        if path == failure_log:
            raise OSError("simulated unreadable journal")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_failure_log)
    summary = cis.summarize_failures(tmp_path)
    assert summary["failure_log_readable"] is False
    assert summary["failure_provenance_complete"] is False
    assert summary["incomplete"] is True


def test_summarize_failures_quarantines_malformed_lines(tmp_path):
    (tmp_path / "failures.jsonl").write_text(
        '\n{"phase":"product_detail","status":1}\n{not-json\n\n', encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 1 and s["by_status"] == {"1": 1}
    assert s["corrupt_records"] == 1
    assert s["failure_provenance_complete"] is False
    assert s["incomplete"] is True


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
        _brand(),
        date_root=tmp_path, resume=False, sleep_ms=0, timeout=1, max_retries=0,
        max_pages=None, max_products=None, fetch_unknown_detail=False,
        bank_dir_name="holder", detail_workers=4, log=lambda *_a, **_k: None,
    )
    assert any(f.get("status") == "worker_crash" for f in failures)


def test_mismatched_detail_id_is_terminal_and_not_written(tmp_path, monkeypatch):
    failures = []

    def fake_fetch(url, **_kwargs):
        if url == ENDPOINT:
            return FetchResult(ok=True, status=200, url=url, text='{"data": {}}', version=4)
        return FetchResult(
            ok=True,
            status=200,
            url=url,
            text='{"data":{"productId":"WRONG"}}',
            version=7,
        )

    monkeypatch.setattr(lib, "fetch_cdr_json", fake_fetch)
    monkeypatch.setattr(lib, "extract_products", lambda _parsed: [{"productId": "P1", "name": "One"}])
    monkeypatch.setattr(lib, "next_link", lambda _parsed, _url: None)
    monkeypatch.setattr(
        lib,
        "classify_product_for_ingest",
        lambda *_args, **_kwargs: (next(iter(lib.DATASET_TO_FOLDER)), None),
    )
    monkeypatch.setattr(lib, "append_failure", lambda _root, entry, lock=None: failures.append(entry))

    summary = lib.ingest_brand(
        _brand(),
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=None,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_args: None,
    )

    assert summary["state"] == "partial"
    assert summary["terminal_detail_failures"] == ["P1"]
    assert [item["status"] for item in failures] == ["detail_fetch_failed"]
    assert not list(tmp_path.rglob("product-detail.json"))


def test_holder_caps_are_recorded_as_incomplete_evidence(tmp_path, monkeypatch):
    failures = []
    monkeypatch.setattr(
        lib,
        "fetch_cdr_json",
        lambda url, **k: FetchResult(
            ok=True, status=200, url=url, text='{"data": {}}', version=4
        ),
    )
    monkeypatch.setattr(
        lib,
        "extract_products",
        lambda parsed: [
            {"productId": "P1", "name": "One", "productCategory": "BUSINESS_LOANS"},
            {"productId": "P2", "name": "Two", "productCategory": "BUSINESS_LOANS"},
        ],
    )
    monkeypatch.setattr(lib, "next_link", lambda parsed, url: None)
    monkeypatch.setattr(
        lib,
        "classify_product_for_ingest",
        lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        lib,
        "append_failure",
        lambda _root, entry, lock=None: failures.append(entry),
    )

    lib.ingest_brand(
        _brand(),
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=None,
        max_products=1,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_a, **_k: None,
    )
    assert [item["status"] for item in failures] == ["max_products_reached"]
    failures.clear()
    lib.ingest_brand(
        _brand(),
        date_root=tmp_path / "page-cap",
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=0,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_a, **_k: None,
    )
    assert [item["status"] for item in failures] == ["max_pages_reached"]


@pytest.mark.parametrize(
    "category, expected_state, expected_unresolved, expected_failures",
    [
        ("BUSINESS_LOANS", "empty", [], []),
        ("NEW_UNMAPPED_CATEGORY", "partial", ["P1"], ["classification_unresolved"]),
    ],
)
def test_catalogue_classification_is_never_silently_dropped(
    tmp_path,
    monkeypatch,
    category,
    expected_state,
    expected_unresolved,
    expected_failures,
):
    failures = []
    monkeypatch.setattr(
        lib,
        "fetch_cdr_json",
        lambda url, **_kwargs: FetchResult(
            ok=True, status=200, url=url, text='{"data": {}}', version=4
        ),
    )
    monkeypatch.setattr(
        lib,
        "extract_products",
        lambda _parsed: [
            {"productId": "P1", "name": "One", "productCategory": category}
        ],
    )
    monkeypatch.setattr(lib, "next_link", lambda _parsed, _url: None)
    monkeypatch.setattr(
        lib,
        "append_failure",
        lambda _root, entry, lock=None: failures.append(entry),
    )

    summary = lib.ingest_brand(
        _brand(),
        date_root=tmp_path,
        resume=False,
        sleep_ms=0,
        timeout=1,
        max_retries=0,
        max_pages=None,
        max_products=None,
        fetch_unknown_detail=False,
        bank_dir_name="holder",
        detail_workers=1,
        log=lambda *_args: None,
    )

    assert summary["state"] == expected_state
    assert summary["unique_product_ids"] == 1
    assert summary["relevant_products"] == 0
    assert summary["classification_unresolved"] == expected_unresolved
    assert [item["status"] for item in failures] == expected_failures


def test_canonical_register_discovery_is_complete(monkeypatch):
    success = FetchResult(
        ok=True, status=200, url="https://register.example/ok", text="{}"
    )
    monkeypatch.setattr(cis, "fetch_cdr_json", lambda *a, **k: success)
    monkeypatch.setattr(
        cis,
        "fetch_json_plain",
        lambda *a, **k: pytest.fail("legacy register endpoints must not be requested"),
    )
    monkeypatch.setattr(
        cis,
        "iter_banking_brands_from_payload",
        lambda _payload: [
            {
                "endpoint_url": "https://holder.example/products",
                "brand_name": "Holder",
                "legal_entity_name": "Holder Ltd",
            }
        ],
    )

    snapshot = cis.collect_register_snapshot(
        timeout=1,
        max_retries=0,
        sleep_ms=0,
        holders_filter=None,
    )
    assert snapshot.register_ok is True
    assert snapshot.register_provenance_complete is True
    assert len(snapshot.register_attempts) == 1
    assert snapshot.register_attempts[0]["ok"] is True


def test_canonical_register_failure_is_incomplete(monkeypatch):
    failure = FetchResult(
        ok=False, status=503, url="https://register.example/fail", text="unavailable"
    )
    monkeypatch.setattr(cis, "fetch_cdr_json", lambda *a, **k: failure)
    monkeypatch.setattr(
        cis,
        "fetch_json_plain",
        lambda *a, **k: pytest.fail("legacy register endpoints must not be requested"),
    )

    snapshot = cis.collect_register_snapshot(
        timeout=1,
        max_retries=0,
        sleep_ms=0,
        holders_filter=None,
    )

    assert snapshot.register_ok is False
    assert snapshot.register_provenance_complete is False
    assert len(snapshot.register_attempts) == 1
    assert snapshot.banking_brands == []


def test_persist_ingest_status_copies_into_exports(tmp_path):
    # The rollup must land in _exports so it survives the Pi RAM-staged copy (Codex).
    run_dir = tmp_path / "2026-06-19"
    (run_dir / "banks").mkdir(parents=True)
    (run_dir / "banks" / "ingest-status.json").write_text('{"total": 2}', encoding="utf-8")
    export_root = tmp_path / "_exports"
    cdr_daily.persist_ingest_status(run_dir, export_root)
    assert (export_root / "ingest-status.json").read_text() == '{"total": 2}'


def test_persist_ingest_status_noop_when_absent(tmp_path):
    run_dir = tmp_path / "2026-06-19"
    run_dir.mkdir()
    export_root = tmp_path / "_exports"
    cdr_daily.persist_ingest_status(run_dir, export_root)  # no banks/ingest-status.json
    assert not (export_root / "ingest-status.json").exists()


def test_summarize_failures_buckets_missing_or_null_as_unknown(tmp_path):
    recs = [{"bank": "x"}, {"phase": None, "status": None}]
    (tmp_path / "failures.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 2
    assert s["by_phase"] == {"unknown": 2}
    assert s["by_status"] == {"unknown": 2}
    assert s["unattributed_records"] == 1
    assert s["failure_provenance_complete"] is False


def test_summarize_failures_marks_blank_provider_as_unattributed(tmp_path):
    (tmp_path / "failures.jsonl").write_text(
        json.dumps({"bank": "   ", "phase": "products_index", "status": 500}) + "\n",
        encoding="utf-8",
    )
    summary = cis.summarize_failures(tmp_path)
    assert summary["by_provider"] == {"unknown": 1}
    assert summary["unattributed_records"] == 1
    assert summary["failure_provenance_complete"] is False


def test_summarize_failures_quarantines_non_object_json_lines(tmp_path):
    # Valid JSON that isn't an object must be skipped, not crash rec.get(...).
    (tmp_path / "failures.jsonl").write_text(
        '[1, 2]\n"a string"\n42\n{"phase":"p","status":1}\n', encoding="utf-8"
    )
    s = cis.summarize_failures(tmp_path)
    assert s["total"] == 1 and s["by_status"] == {"1": 1}
    assert s["corrupt_records"] == 3
    assert s["failure_provenance_complete"] is False
