"""Read-only report regressions using sanitized retained November 13 status."""
import copy
import json
from pathlib import Path
import subprocess
import sys

from scripts import pi_coverage_report as report


def captured_status():
    return json.loads((Path(__file__).parent / "fixtures" / "coverage-report-20261113.json").read_text())


def test_current_real_schema_counts_each_failure_once():
    value = report.status_report(captured_status())
    assert value["total"] == sum(value["providers"].values()) == 11
    assert len(value["providers"]) == 8
    assert sum(value["samples"].values()) == 11
    assert value["sample_complete"] is True
    assert value["samples"][("MoveBank", "products_index", "invalid_response", "conflicting_product_identity")] == 1
    assert value["categories"]["MoveBank"] == {"unknown_internal": 1}


def test_uid_resolves_through_provider_states_without_counting_state_again():
    status = captured_status()
    for row in status["unresolved_requests"]:
        row.pop("provider_dir")
    value = report.status_report(status)
    assert value["total"] == 11
    assert {k[0] for k in value["samples"]} == set(value["providers"])
    status.pop("by_provider")
    assert report.status_report(status)["total"] == 11


def test_partial_request_sample_does_not_reduce_aggregate_count():
    status = captured_status()
    status["unresolved_requests"] = status["unresolved_requests"][:1]
    status["unresolved_requests_complete"] = False
    value = report.status_report(status)
    assert value["total"] == 11 and sum(value["samples"].values()) == 1
    assert value["sample_complete"] is False


def test_unknown_or_inconsistent_schema_never_reports_complete_zero():
    assert report.status_report({"total": 11, "future_failures": []})["total"] is None
    assert report.status_report({"total": 0, "by_provider": {}})["total"] is None
    status = captured_status()
    status["by_provider"] = {}
    assert report.status_report(status)["total"] is None
    status.update(total=0, failure_provenance_complete=False)
    assert report.status_report(status)["total"] is None
    assert report.status_report({"total": 0, "by_provider": {}, "failure_provenance_complete": True})["total"] == 0
    status = captured_status()
    status.update(total=0, by_provider={})
    assert report.status_report(status)["total"] is None


def test_capped_and_malformed_samples_stay_explicit(monkeypatch):
    monkeypatch.setattr(report, "MAX_REQUESTS", 1)
    assert report.status_report(captured_status())["capped"] is True
    status = captured_status()
    status["unresolved_requests"] = [None]
    value = report.status_report(status)
    assert value["total"] == 11 and value["sample_unknown"] == 1
    assert value["sample_complete"] is False


def test_cli_sanitizes_unknown_fields_and_reports_real_totals(tmp_path, capsys):
    status = captured_status()
    status["private_metadata"] = {"bank": "DO-NOT-PRINT", "phase": "secret"}
    status["unresolved_requests"][0]["url"] = "https://host/?token=secret"
    status["unresolved_requests"][0]["snippet"] = "DO-NOT-PRINT"
    status["unresolved_requests"][0]["status"] = "https://host/?token=secret\n" + "X" * 50
    target = tmp_path / "runs" / "2026-11-13" / "_exports"
    target.mkdir(parents=True)
    (target / "ingest-status.json").write_text(json.dumps(status))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert report.main([str(tmp_path), "14"]) == 0
    output = capsys.readouterr().out
    assert "failure_rows=11" in output and "providers=8" in output
    assert "DO-NOT-PRINT" not in output and "secret" not in output and "X" * 40 not in output
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_cli_schema_drift_is_unknown_and_nonzero(tmp_path, capsys):
    target = tmp_path / "runs" / "2026-11-13" / "_exports"
    target.mkdir(parents=True)
    (target / "ingest-status.json").write_text('{"total":11,"future_failures":[]}')
    assert report.main([str(tmp_path)]) == 2
    assert "failure_rows=UNKNOWN" in capsys.readouterr().out


def test_standalone_isolated_stdin_transport(tmp_path):
    target = tmp_path / "runs" / "2026-11-13" / "_exports"
    target.mkdir(parents=True)
    (target / "ingest-status.json").write_text(json.dumps(captured_status()))
    result = subprocess.run([sys.executable, "-I", "-", str(tmp_path)],
                            input=Path(report.__file__).read_bytes(), cwd=tmp_path,
                            capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    assert b"failure_rows=11" in result.stdout and b"providers=8" in result.stdout


def test_journal_fallback_never_sums_revision_duplicates(tmp_path):
    row = copy.deepcopy(captured_status()["unresolved_requests"][0])
    row["bank"] = row.pop("provider_dir")
    for root in (tmp_path, tmp_path / "_revisions" / "retained"):
        (root / "banks").mkdir(parents=True)
        (root / "banks" / "failures.jsonl").write_text(json.dumps(row) + "\n")
    value, status = report.day_report(str(tmp_path))
    assert status is None and value["total"] == 1
    assert value["source"] == "primary-journal"


def test_journal_large_line_is_bounded_and_unknown(tmp_path):
    path = tmp_path / "failures.jsonl"
    path.write_bytes(b"x" * ((64 << 10) + 1))
    value = report.journal_report(path)
    assert value["total"] is None and value["capped"] is True
